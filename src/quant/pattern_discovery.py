"""
PatternDiscoveryEngine — 每只股票独立的模式发现引擎

核心循环:
  历史K线 → 模式发现 → 预测下一日 → 与实际对比 → 偏差回馈 → 迭代收敛

三种模式类型:
  1. K线形态: 锤子线/吞没/十字星/晨星/暮星
  2. 技术指标: RSI背离/MACD金叉死叉/布林带突破
  3. 统计模式: 均值回归/动量延续/波动率突破
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, field
from collections import defaultdict
import json
import sqlite3
import math


@dataclass
class PatternMatch:
    """一次模式匹配结果"""
    pattern_type: str          # candlestick / rsi_divergence / macd_cross / ...
    pattern_sig: str           # 模式签名(用于去重)
    direction: str             # up / down / flat
    confidence: float          # 0~1
    price_target: float        # 预测价格
    params: dict = field(default_factory=dict)


@dataclass
class Prediction:
    """一次预测"""
    stock_code: str
    trade_date: str            # 预测的目标日期
    direction: str             # up / down / flat
    confidence: float          # 0~1
    predicted_price: float
    engine_version: str
    patterns_used: list = field(default_factory=list)


@dataclass 
class ConvergenceStats:
    """收敛统计"""
    total_predictions: int = 0
    correct: int = 0
    accuracy: float = 0.0
    avg_error_pct: float = 0.0
    convergence_score: float = 0.0  # 0~1, 越高越收敛
    best_pattern: str = ""
    best_accuracy: float = 0.0


class PatternDiscoveryEngine:
    """
    单只股票的模式发现引擎（每只股票一个独立实例）
    
    工作流程:
      1. fit(kline_df) — 用历史数据训练
      2. discover_patterns() — 扫描历史发现可重复模式
      3. predict() — 基于当前状态预测下一日
      4. feedback(actual) — 与实际对比，更新模式库
      5. evolve() — 淘汰低效模式，迭代收敛
    """
    
    def __init__(self, stock_code: str, db_path: str = ""):
        self.stock_code = stock_code
        self.db_path = db_path
        self.df: Optional[pd.DataFrame] = None
        self.version = "v2.0"
        self.patterns: Dict[str, list] = defaultdict(list)
        self.convergence = ConvergenceStats()
        self._loaded = False
        # 自适应参数
        self.volatility_threshold = 1.0  # 动态调整
        
    # ── 核心训练 ──
    
    def fit(self, kline_df: pd.DataFrame):
        """加载K线数据并计算衍生特征"""
        if kline_df.empty or len(kline_df) < 30:
            return False
        self.df = kline_df.sort_values("trade_date").copy()
        self._compute_features()
        self._loaded = True
        # 尝试从数据库加载已有模式
        self._load_patterns_from_db()
        return True
    
    def _compute_features(self):
        """计算技术指标特征（含自适应阈值）"""
        df = self.df
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values
        
        # 收益率
        df["return"] = df["close"].pct_change() * 100
        
        # ATR (Average True Range) — 用于自适应阈值
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]  # 第一天用自己代替
        df["tr"] = np.maximum(
            high - low,
            np.maximum(
                np.abs(high - prev_close),
                np.abs(low - prev_close)
            )
        )
        df["atr"] = df["tr"].rolling(14).mean()
        self.volatility_threshold = max(0.5, df["atr"].mean() / df["close"].mean() * 100) if df["atr"].mean() > 0 else 1.0
        
        # RSI
        delta = df["close"].diff()
        gain = delta.clip(0)
        loss = -delta.clip(0)
        avg_g = gain.rolling(14).mean()
        avg_l = loss.rolling(14).mean()
        rs = avg_g / avg_l.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        
        # MACD
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        df["macd_dif"] = ema12 - ema26
        df["macd_dea"] = df["macd_dif"].ewm(span=9).mean()
        df["macd_bar"] = 2 * (df["macd_dif"] - df["macd_dea"])
        
        # 布林带
        df["boll_mid"] = close_ma = df["close"].rolling(20).mean()
        df["boll_std"] = df["close"].rolling(20).std()
        df["boll_up"] = df["boll_mid"] + 2 * df["boll_std"]
        df["boll_dn"] = df["boll_mid"] - 2 * df["boll_std"]
        df["boll_pos"] = (close - df["boll_dn"]) / (df["boll_up"] - df["boll_dn"]).replace(0, np.nan)
        
        # 成交量变化
        df["vol_ma5"] = df["volume"].rolling(5).mean()
        df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan)
        
        # 波动率
        df["volatility"] = df["return"].rolling(5).std()
        
        # 次日收益(用于监督学习)
        df["next_return"] = df["return"].shift(-1)
        # NaN 保持 NaN（最后一行无次日数据），discover 阶段据此跳过，避免产生假标签
        df["next_direction"] = df["next_return"].apply(
            lambda x: "up" if pd.notna(x) and x > 1.0 else "down" if pd.notna(x) and x < -1.0 else "flat" if pd.notna(x) else np.nan)
        
        # 次日收盘价
        df["next_close"] = df["close"].shift(-1)
        
        self.df = df
    
    # ── 模式发现 ──
    
    def discover_patterns(self) -> int:
        """扫描历史数据，发现所有可重复模式"""
        if not self._loaded or self.df is None or len(self.df) < 30:
            return 0
        
        count = 0
        # 每种模式类型独立发现
        for method in [
            self._discover_candlestick,
            self._discover_rsi_divergence,
            self._discover_macd_cross,
            self._discover_bollinger_break,
            self._discover_volume_spike,
            self._discover_momentum,
        ]:
            try:
                found = method()
                count += found
            except Exception:
                continue
        
        # 保存到数据库
        self._save_patterns_to_db()
        return count
    
    def _discover_candlestick(self) -> int:
        """发现K线形态模式"""
        df = self.df
        found = 0
        for i in range(5, len(df) - 1):
            if pd.isna(df.iloc[i]["next_direction"]):
                continue
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            direction = df.iloc[i]["next_direction"]
            
            # 锤子线: 下影线>实体2倍, 上影线短
            body = abs(curr["close"] - curr["open"])
            lower_shadow = min(curr["open"], curr["close"]) - curr["low"]
            upper_shadow = curr["high"] - max(curr["open"], curr["close"])
            if (body > 0 and lower_shadow > body * 2 and upper_shadow < body * 0.3
                and prev["close"] > curr["close"]):
                sig = f"hammer_{i}"
                self._add_pattern("candlestick", sig, "up" if direction == "up" else "flat", i)
                found += 1
            
            # 吞没形态
            prev_body = abs(prev["close"] - prev["open"])
            curr_body = abs(curr["close"] - curr["open"])
            if (body > 0 and prev_body > 0 and curr_body > prev_body * 1.2):
                prev_bear = prev["close"] < prev["open"]  # 前阴
                curr_bull = curr["close"] > curr["open"]   # 后阳
                if prev_bear and curr_bull and curr["open"] < prev["close"] and curr["close"] > prev["open"]:
                    sig = f"engulfing_bull_{i}"
                    self._add_pattern("candlestick", sig, direction, i)
                    found += 1
            
            # 十字星: 实体极小
            if body > 0 and body / (df.iloc[i]["high"] - df.iloc[i]["low"]) < 0.1:
                sig = f"doji_{i}"
                # 十字星后通常反转
                pred_dir = "up" if prev["close"] < curr["close"] else "down"
                self._add_pattern("candlestick", sig, pred_dir, i)
                found += 1
        return found
    
    def _discover_rsi_divergence(self) -> int:
        """发现RSI背离模式"""
        df = self.df
        found = 0
        for i in range(20, len(df) - 1):
            if pd.isna(df.iloc[i]["rsi"]) or pd.isna(df.iloc[i]["next_direction"]):
                continue
            # 顶背离: 价格新高 + RSI新低
            p20_max = df.iloc[i-20:i+1]["close"].max()
            r20_max = df.iloc[i-20:i+1]["rsi"].max()
            p_max_idx = df.iloc[i-20:i+1]["close"].idxmax()
            r_max_idx = df.iloc[i-20:i+1]["rsi"].idxmax()
            if (p_max_idx < r_max_idx and df.iloc[i]["close"] > df.iloc[p_max_idx]["close"] * 0.98
                and df.iloc[i]["rsi"] < df.iloc[r_max_idx]["rsi"] * 0.95):
                sig = f"rsi_div_top_{i}"
                self._add_pattern("rsi_divergence", sig, "down", i)
                found += 1
            # 底背离
            p20_min = df.iloc[i-20:i+1]["close"].min()
            r20_min = df.iloc[i-20:i+1]["rsi"].min()
            p_min_idx = df.iloc[i-20:i+1]["close"].idxmin()
            r_min_idx = df.iloc[i-20:i+1]["rsi"].idxmin()
            if (p_min_idx < r_min_idx and df.iloc[i]["close"] < df.iloc[p_min_idx]["close"] * 1.02
                and df.iloc[i]["rsi"] > df.iloc[r_min_idx]["rsi"] * 1.05):
                sig = f"rsi_div_bottom_{i}"
                self._add_pattern("rsi_divergence", sig, "up", i)
                found += 1
        return found
    
    def _discover_macd_cross(self) -> int:
        """发现MACD金叉/死叉模式"""
        df = self.df
        found = 0
        for i in range(26, len(df) - 1):
            if pd.isna(df.iloc[i]["macd_bar"]) or pd.isna(df.iloc[i-1]["macd_bar"]):
                continue
            # 金叉: MACD柱从负转正
            if df.iloc[i-1]["macd_bar"] <= 0 and df.iloc[i]["macd_bar"] > 0:
                sig = f"macd_golden_{i}"
                self._add_pattern("macd_cross", sig, "up", i)
                found += 1
            # 死叉
            if df.iloc[i-1]["macd_bar"] >= 0 and df.iloc[i]["macd_bar"] < 0:
                sig = f"macd_dead_{i}"
                self._add_pattern("macd_cross", sig, "down", i)
                found += 1
        return found
    
    def _discover_bollinger_break(self) -> int:
        """发现布林带突破模式"""
        df = self.df
        found = 0
        for i in range(20, len(df) - 1):
            if pd.isna(df.iloc[i]["boll_pos"]) or pd.isna(df.iloc[i]["next_direction"]):
                continue
            # 突破上轨(超买) → 回调
            if df.iloc[i]["boll_pos"] > 1.0:
                sig = f"boll_overbought_{i}"
                self._add_pattern("bollinger", sig, "down", i)
                found += 1
            # 跌破下轨(超卖) → 反弹
            if df.iloc[i]["boll_pos"] < 0:
                sig = f"boll_oversold_{i}"
                self._add_pattern("bollinger", sig, "up", i)
                found += 1
        return found
    
    def _discover_volume_spike(self) -> int:
        """发现成交量异常模式"""
        df = self.df
        found = 0
        for i in range(5, len(df) - 1):
            if pd.isna(df.iloc[i]["vol_ratio"]) or pd.isna(df.iloc[i]["next_direction"]):
                continue
            # 放量 + 上涨 → 动量延续
            if df.iloc[i]["vol_ratio"] > 1.5 and df.iloc[i]["return"] > 2:
                sig = f"vol_surge_up_{i}"
                self._add_pattern("volume", sig, "up", i)
                found += 1
            # 放量 + 下跌 → 继续跌
            if df.iloc[i]["vol_ratio"] > 1.5 and df.iloc[i]["return"] < -2:
                sig = f"vol_surge_down_{i}"
                self._add_pattern("volume", sig, "down", i)
                found += 1
            # 缩量 + 窄幅 → 变盘
            if df.iloc[i]["vol_ratio"] < 0.5 and abs(df.iloc[i]["return"]) < 0.5:
                sig = f"vol_quiet_{i}"
                self._add_pattern("volume", sig, "flat", i)
                found += 1
        return found
    
    def _discover_momentum(self) -> int:
        """发现动量延续/反转模式"""
        df = self.df
        found = 0
        for i in range(3, len(df) - 1):
            if pd.isna(df.iloc[i]["next_direction"]):
                continue
            # 连涨3天 → 第4天?
            if all(df.iloc[i-j]["return"] > 0 for j in range(3) if not pd.isna(df.iloc[i-j]["return"])):
                sig = f"consecutive_up_{i}"
                self._add_pattern("momentum", sig, df.iloc[i]["next_direction"], i)
                found += 1
            # 连跌3天
            if all(df.iloc[i-j]["return"] < 0 for j in range(3) if not pd.isna(df.iloc[i-j]["return"])):
                sig = f"consecutive_down_{i}"
                self._add_pattern("momentum", sig, df.iloc[i]["next_direction"], i)
                found += 1
        return found
    
    def _add_pattern(self, ptype: str, sig: str, direction: str, idx: int):
        """添加一次模式匹配结果"""
        self.patterns[ptype].append({
            "sig": sig,
            "direction": direction,
            "idx": idx,
            "date": str(self.df.iloc[idx]["trade_date"]),
            "actual_dir": str(self.df.iloc[idx]["next_direction"]),
            "correct": direction == str(self.df.iloc[idx]["next_direction"])
        })
    
    # ── 模式库管理 ──
    
    def _aggregate_patterns(self) -> dict:
        """聚合相同模式，计算命中率"""
        from collections import defaultdict
        agg = defaultdict(lambda: {"hits": 0, "total": 0, "directions": defaultdict(int)})
        for ptype, matches in self.patterns.items():
            for m in matches:
                # 跳过DB加载的摘要模式(已聚合)
                if m.get("from_db"):
                    continue
                # 用模式类型+方向作为聚合键
                key = f"{ptype}_{m['direction']}"
                agg[key]["total"] += 1
                if m.get("correct", False):
                    agg[key]["hits"] += 1
                agg[key]["directions"][m["actual_dir"]] += 1
        return dict(agg)
    
    def _load_patterns_from_db(self):
        """从数据库加载历史模式"""
        if not self.db_path:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT pattern_type, pattern_sig, direction, hit_rate, sample_count "
                "FROM pattern_library WHERE stock_code=? AND is_active=1",
                (self.stock_code,)).fetchall()
            for row in rows:
                self.patterns[row[0]].append({
                    "sig": row[1], "direction": row[2],
                    "hit_rate": row[3], "sample_count": row[4],
                    "from_db": True
                })
            conn.close()
        except Exception:
            pass
    
    def _save_patterns_to_db(self):
        """将发现的模式持久化到数据库"""
        if not self.db_path:
            return
        agg = self._aggregate_patterns()
        try:
            conn = sqlite3.connect(self.db_path)
            now = datetime.now().strftime("%Y-%m-%d")
            for key, stats in agg.items():
                parts = key.rsplit("_", 1)
                ptype = parts[0]
                direction = parts[1] if len(parts) > 1 else "flat"
                hit_rate = stats["hits"] / stats["total"] if stats["total"] > 0 else 0
                # UPSERT：已存在模式仅更新命中率/样本数/last_seen，保留 first_seen
                conn.execute(
                    """INSERT INTO pattern_library
                    (stock_code, pattern_type, pattern_sig, direction,
                     hit_rate, sample_count, first_seen, last_seen, is_active)
                    VALUES (?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(stock_code, pattern_type, pattern_sig) DO UPDATE SET
                      direction=excluded.direction,
                      hit_rate=excluded.hit_rate,
                      sample_count=excluded.sample_count,
                      last_seen=excluded.last_seen,
                      is_active=1""",
                    (self.stock_code, ptype, key, direction,
                     round(hit_rate, 4), stats["total"], now, now))
            conn.commit()
            conn.close()
        except Exception:
            pass
    
    # ── 预测 ──
    
    # ── 模式显著性 ──

    @staticmethod
    def _is_significant(hits: int, total: int, min_samples: int = 10,
                        alpha: float = 0.05) -> bool:
        """
        二项检验：模式胜率是否显著高于 0.5（单侧，α=0.05）。
        样本量不足或无 scipy 时退化为 min_samples 门槛。
        """
        if total < min_samples:
            return False
        try:
            from scipy.stats import binomtest
            return binomtest(hits, total, p=0.5, alternative="greater").pvalue < alpha
        except ImportError:
            return total >= min_samples

    def predict(self) -> Optional[Prediction]:
        """增强预测：自适应阈值 + 集成投票 + 模式衰减"""
        if not self._loaded or self.df is None or len(self.df) < 30:
            return None
        
        df = self.df; latest = df.iloc[-1]
        th = self.volatility_threshold  # 自适应阈值
        
        current_state = {
            "return": latest["return"] if not pd.isna(latest.get("return")) else 0,
            "rsi": latest["rsi"] if not pd.isna(latest.get("rsi")) else 50,
            "macd_bar": latest["macd_bar"] if not pd.isna(latest.get("macd_bar")) else 0,
            "macd_dif": latest["macd_dif"] if not pd.isna(latest.get("macd_dif")) else 0,
            "boll_pos": latest["boll_pos"] if not pd.isna(latest.get("boll_pos")) else 0.5,
            "vol_ratio": latest["vol_ratio"] if not pd.isna(latest.get("vol_ratio")) else 1,
            "volatility": latest["volatility"] if not pd.isna(latest.get("volatility")) else 0,
            "close": latest["close"],
        }
        
        patterns_found = []
        direction_scores = {"up": 0, "down": 0, "flat": 0}
        weights_used = []
        
        # 1. RSI信号（阈值收紧至更极端值）
        rsi = current_state["rsi"]
        if isinstance(rsi, (int, float)) and not math.isnan(rsi):
            if rsi > 75:
                direction_scores["down"] += 0.30; patterns_found.append("RSI超买(>75)")
            elif rsi > 65:
                direction_scores["down"] += 0.15; patterns_found.append("RSI偏买")
            elif rsi < 25:
                direction_scores["up"] += 0.30; patterns_found.append("RSI超卖(<25)")
            elif rsi < 35:
                direction_scores["up"] += 0.15; patterns_found.append("RSI偏卖")
        
        # 2. MACD柱+快慢线双确认
        bar = current_state["macd_bar"]
        dif = current_state["macd_dif"]
        if isinstance(bar, (int, float)) and not math.isnan(bar):
            if bar > 0 and dif > 0:
                direction_scores["up"] += 0.25; patterns_found.append("MACD双多")
            elif bar < 0 and dif < 0:
                direction_scores["down"] += 0.25; patterns_found.append("MACD双空")
            elif bar > 0:
                direction_scores["up"] += 0.10
            elif bar < 0:
                direction_scores["down"] += 0.10
        
        # 3. 布林带
        bp = current_state["boll_pos"]
        if isinstance(bp, (int, float)) and not math.isnan(bp):
            if bp > 1.0: direction_scores["down"] += 0.20; patterns_found.append("布林上轨外")
            elif bp > 0.85: direction_scores["down"] += 0.10
            elif bp < 0: direction_scores["up"] += 0.20; patterns_found.append("布林下轨外")
            elif bp < 0.15: direction_scores["up"] += 0.10
        
        # 4. 量价配合（使用自适应阈值）
        ret = current_state["return"]
        vr = current_state["vol_ratio"]
        if isinstance(vr, (int, float)) and not math.isnan(vr) and isinstance(ret, (int, float)) and not math.isnan(ret):
            if vr > 1.5 and ret > th: direction_scores["up"] += 0.20; patterns_found.append("放量上涨")
            elif vr > 1.5 and ret < -th: direction_scores["down"] += 0.20; patterns_found.append("放量下跌")
            elif vr < 0.5 and abs(ret) < th*0.5: direction_scores["flat"] += 0.15; patterns_found.append("缩量盘整")
        
        # 5. 历史模式集成（带衰减权重 + 显著性筛选）
        agg = self._aggregate_patterns()
        pattern_votes = {"up": 0, "down": 0, "flat": 0}
        for key, stats in agg.items():
            if stats["total"] < 3: continue
            hit_rate = stats["hits"] / stats["total"]
            # 衰减系数：样本越多越可信，但不超过0.6权重
            weight = min(0.6, hit_rate * min(1.0, stats["total"] / 10))
            # 统计不显著的模式（样本不足或胜率不显著>0.5）权重减半
            if not self._is_significant(stats["hits"], stats["total"]):
                weight *= 0.5
            dir_key = key.split("_")[-1]
            if dir_key in pattern_votes:
                pattern_votes[dir_key] += weight
        
        total_pv = sum(pattern_votes.values())
        if total_pv > 0:
            best_pattern_dir = max(pattern_votes, key=pattern_votes.get)
            direction_scores[best_pattern_dir] += pattern_votes[best_pattern_dir] * 0.5
            patterns_found.append(f"模式投票→{best_pattern_dir}")
        
        # 6. 波动率收缩/扩张信号
        vol = current_state["volatility"]
        if isinstance(vol, (int, float)) and not math.isnan(vol):
            # 对比5日前波动率
            vol5 = df["volatility"].iloc[-5] if len(df) >= 5 and not pd.isna(df["volatility"].iloc[-5]) else vol
            if vol < vol5 * 0.7: direction_scores["flat"] += 0.15; patterns_found.append("波动收缩")
            elif vol > vol5 * 1.5: direction_scores["flat"] -= 0.10  # 波动扩张→方向性突破
        
        # 决策
        total_score = sum(direction_scores.values())
        if total_score > 0:
            for k in direction_scores: direction_scores[k] /= total_score
        
        best_dir = max(direction_scores, key=direction_scores.get)
        confidence = direction_scores[best_dir]
        
        # 预测价格（ATR自适应）
        last_close = float(current_state["close"])
        atr_pct = th / 100  # ATR百分比
        if best_dir == "up": pred_price = last_close * (1 + atr_pct)
        elif best_dir == "down": pred_price = last_close * (1 - atr_pct)
        else: pred_price = last_close
        
        next_date = self._next_trade_date(df.iloc[-1]["trade_date"])
        
        return Prediction(
            stock_code=self.stock_code, trade_date=next_date,
            direction=best_dir, confidence=min(confidence, 0.95),
            predicted_price=round(pred_price, 2),
            engine_version=self.version, patterns_used=patterns_found[:6]
        )
    
    def _next_trade_date(self, last_date) -> str:
        """估算下一交易日"""
        try:
            d = datetime.strptime(str(last_date), "%Y-%m-%d") + timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            return d.strftime("%Y-%m-%d")
        except:
            return datetime.now().strftime("%Y-%m-%d")
    
    # ── 反馈与迭代 ──
    
    def feedback(self, prediction: Prediction, actual_close: float):
        """
        反馈: 将预测与实际对比，计算偏差
        返回偏差统计
        """
        actual_return = (actual_close - prediction.predicted_price) / prediction.predicted_price * 100
        if actual_return > 1:
            actual_dir = "up"
        elif actual_return < -1:
            actual_dir = "down"
        else:
            actual_dir = "flat"
        
        correct = actual_dir == prediction.direction
        error_pct = abs(actual_return)
        
        # 保存到数据库
        if self.db_path:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    """INSERT INTO prediction_log
                    (stock_code, trade_date, direction, confidence, predicted_price,
                     actual_direction, actual_price, correct, error_pct, engine_version)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (self.stock_code, prediction.trade_date, prediction.direction,
                     prediction.confidence, prediction.predicted_price,
                     actual_dir, actual_close, int(correct), round(error_pct, 2),
                     self.version))
                conn.commit()
                conn.close()
            except Exception:
                pass
        
        # 更新收敛统计
        self.convergence.total_predictions += 1
        if correct:
            self.convergence.correct += 1
        self.convergence.accuracy = self.convergence.correct / self.convergence.total_predictions
        self.convergence.avg_error_pct = (
            (self.convergence.avg_error_pct * (self.convergence.total_predictions - 1) + error_pct)
            / self.convergence.total_predictions
        )
        self.convergence.convergence_score = self._calc_convergence()
        
        return {
            "actual_dir": actual_dir,
            "correct": correct,
            "error_pct": round(error_pct, 2),
            "accuracy": round(self.convergence.accuracy, 4),
            "total_tests": self.convergence.total_predictions
        }
    
    def _calc_convergence(self) -> float:
        """计算收敛分数 0~1，越高越收敛"""
        if self.convergence.total_predictions < 5:
            return 0.0
        # 查看近期 N 次预测的准确率稳定性
        n = min(20, self.convergence.total_predictions)
        # 用准确率本身 + 样本量作为收敛指标
        score = self.convergence.accuracy * min(1.0, self.convergence.total_predictions / 50)
        return round(score, 4)
    
    # ── 历史回测 ──
    
    def backtest(self, window: int = 60, step: int = 1,
                 cost_pct: float = 0.1) -> dict:
        """
        滑动窗口回测: 用历史数据模拟预测-反馈循环

        参数:
            window: 训练窗口大小(交易日)
            step: 滑动步长
            cost_pct: 单次换仓交易成本（%），默认 0.1%（双边）

        返回:
            {accuracy, total, correct, total_return, max_drawdown, sharpe,
             trades, per_pattern, details}
        """
        if not self._loaded or self.df is None or len(self.df) < window + 10:
            return {"error": f"数据不足: loaded={self._loaded}, len={len(self.df) if self.df is not None else 0}, need={window+10}"}
        
        df = self.df
        results = []
        
        for end_idx in range(window, len(df) - 1, step):
            # 训练窗口: [end_idx-window, end_idx)
            train_df = df.iloc[end_idx - window:end_idx]
            
            # 创建临时引擎
            temp_engine = PatternDiscoveryEngine(self.stock_code)
            temp_engine.fit(train_df)
            temp_engine.discover_patterns()
            
            # 预测: temp_engine 用训练窗口最后一根K线(end_idx-1)的状态预测 end_idx 日
            pred = temp_engine.predict()
            if pred is None:
                continue
            
            # 实际值: end_idx 日相对 end_idx-1 日的收益（与预测目标日对齐，避免错位一天）
            actual = df.iloc[end_idx]
            prev_close = float(df.iloc[end_idx - 1]["close"])
            actual_close = float(actual["close"])
            actual_ret = (actual_close - prev_close) / prev_close * 100
            actual_dir = "up" if actual_ret > 1 else "down" if actual_ret < -1 else "flat"
            correct = 1 if actual_dir == pred.direction else 0
            
            results.append({
                "date": str(actual["trade_date"]),
                "pred_dir": pred.direction,
                "actual_dir": actual_dir,
                "actual_ret": round(actual_ret, 3),
                "confidence": round(pred.confidence, 3),
                "pattern": (pred.patterns_used[0] if pred.patterns_used else "无"),
                "correct": correct
            })
        
        if not results:
            return {"error": "回测无结果", "total": 0, "correct": 0, "accuracy": 0.0, "details": []}
        
        total = len(results)
        correct = sum(r["correct"] for r in results)
        accuracy = correct / total if total > 0 else 0
        
        # ── 交易模拟（含换仓成本）──
        equity, position, trades = 1.0, 0, 0
        curve = [1.0]
        for r in results:
            target = 1 if r["pred_dir"] == "up" else 0
            if target != position:
                equity *= (1 - cost_pct / 100)
                trades += 1
                position = target
            equity *= (1 + r["actual_ret"] / 100) if position else 1.0
            curve.append(equity)
        curve = np.array(curve)
        # 最大回撤
        peak = np.maximum.accumulate(curve)
        max_drawdown = float(((curve - peak) / peak).min()) if len(curve) > 1 else 0.0
        # 夏普比率（日收益年化，252 交易日）
        rets = np.diff(curve) / curve[:-1] if len(curve) > 1 else np.array([0.0])
        sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
        # 分模式胜率（按预测使用的主要模式聚合）
        per_pattern: dict = {}
        for r in results:
            p = r["pattern"]
            if p not in per_pattern:
                per_pattern[p] = {"hits": 0, "total": 0}
            per_pattern[p]["hits"] += r["correct"]
            per_pattern[p]["total"] += 1
        per_pattern = {p: {**s, "rate": round(s["hits"] / s["total"], 3)}
                       for p, s in sorted(per_pattern.items(),
                                          key=lambda kv: -kv[1]["hits"] / max(kv[1]["total"], 1))[:5]}
        
        return {
            "total": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "total_return": round(equity - 1, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe": round(sharpe, 3),
            "trades": trades,
            "per_pattern": per_pattern,
            "details": results[-30:],  # 最近30条
            "engine_version": self.version
        }
    
    # ── 状态报告 ──
    
    def summary(self) -> dict:
        """引擎状态摘要"""
        agg = self._aggregate_patterns()
        best_pattern = ""
        best_rate = 0
        for key, stats in agg.items():
            rate = stats["hits"] / stats["total"] if stats["total"] > 0 else 0
            if rate > best_rate and stats["total"] >= 3:
                best_rate = rate
                best_pattern = key
        
        return {
            "stock_code": self.stock_code,
            "version": self.version,
            "data_days": len(self.df) if self.df is not None else 0,
            "patterns_found": sum(len(v) for v in self.patterns.values()),
            "pattern_types": list(self.patterns.keys()),
            "convergence": {
                "total_predictions": self.convergence.total_predictions,
                "accuracy": self.convergence.accuracy,
                "avg_error_pct": self.convergence.avg_error_pct,
                "convergence_score": self.convergence.convergence_score,
            },
            "best_pattern": best_pattern,
            "best_pattern_accuracy": best_rate,
            "is_converged": self.convergence.convergence_score > 0.6
        }
