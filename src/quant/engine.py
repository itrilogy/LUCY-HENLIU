"""
衡流 · HengLiu（QuantFlow）— 量化分析引擎
提供: GMM市场状态分类、马尔可夫转移矩阵、动量分析、因子评分
"""

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
import sqlite3
from typing import Optional


class RegimeClassifier:
    """
    GMM 市场状态分类器
    基于收益率序列将市场分为 4 种典型状态：牛市/熊市/震荡/低迷
    """
    
    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        self.gmm: Optional[GaussianMixture] = None
        self.scaler = StandardScaler()
        self.labels: Optional[np.ndarray] = None
        self.regime_names = {0: "🐻 熊市", 1: "📊 震荡", 2: "📈 牛市", 3: "😴 低迷"}
        self._fitted = False

    def fit(self, kline_df: pd.DataFrame):
        """基于日收益率 + 换手率 + 波动率进行 GMM 聚类"""
        df = kline_df.copy().sort_values("trade_date")
        if len(df) < 30:
            return
        
        # 特征工程
        df["return"] = df["close"].pct_change() * 100  # 日收益率%
        df["volatility"] = df["return"].rolling(5).std()  # 5日波动率
        df["volume_ma"] = df["volume"].rolling(5).mean()
        df["volume_ratio"] = df["volume"] / df["volume_ma"].replace(0, np.nan)
        
        feat = df[["return", "volatility", "volume_ratio"]].dropna().values
        if len(feat) < 30:
            return
        
        # 标准化 + GMM（组件数不超过样本数；feat 已保证 >= 30 行）
        X = self.scaler.fit_transform(feat)
        self.gmm = GaussianMixture(n_components=min(self.n_regimes, len(feat)),
                                    random_state=42, max_iter=500)
        self.labels = self.gmm.fit_predict(X)
        
        # 给regime排序：按平均收益率从高到低命名
        label_means = []
        for i in range(self.gmm.n_components):
            mask = self.labels == i
            if mask.sum() > 0:
                label_means.append((i, feat[mask, 0].mean()))
            else:
                label_means.append((i, -999))
        label_means.sort(key=lambda x: x[1], reverse=True)
        
        mapping = {}
        names = ["📈 牛市", "📊 震荡", "😴 低迷", "🐻 熊市"]
        for idx, (orig_label, _) in enumerate(label_means):
            mapping[orig_label] = names[idx] if idx < len(names) else f"状态{idx}"
        
        self.regime_names = mapping
        self._fitted = True

    def predict(self, return_val: float, volatility: float, volume_ratio: float) -> str:
        """预测当前状态"""
        if not self._fitted or self.gmm is None:
            return "⚪ 未知"
        X = self.scaler.transform([[return_val, volatility, volume_ratio]])
        label = self.gmm.predict(X)[0]
        return self.regime_names.get(label, f"状态{label}")

    def get_regime_series(self, kline_df: pd.DataFrame) -> list:
        """返回每日状态序列 (date, regime_name)"""
        df = kline_df.copy().sort_values("trade_date")
        if not self._fitted or len(df) < 30:
            return []
        df["ret"] = df["close"].pct_change() * 100
        df["vol"] = df["ret"].rolling(5).std()
        df["vma"] = df["volume"].rolling(5).mean()
        df["vr"] = df["volume"] / df["vma"].replace(0, np.nan)
        feat = df[["ret", "vol", "vr"]].dropna()
        if feat.empty:
            return []
        X = self.scaler.transform(feat.values)
        labels = self.gmm.predict(X)
        dates = df.loc[feat.index, "trade_date"].values
        return [(d, self.regime_names.get(l, f"状态{l}")) for d, l in zip(dates, labels)]


class MarkovTransition:
    """
    马尔可夫转移矩阵
    计算状态转移概率，判断市场持续性/反转概率
    """
    
    def __init__(self, n_states: int = 3):
        self.n_states = n_states
        self.transition_matrix: Optional[np.ndarray] = None
        self.steady_state: Optional[np.ndarray] = None
        self.states: list = ["下跌", "盘整", "上涨"]

    def fit(self, returns: np.ndarray):
        """基于收益率序列构建3态马尔可夫链"""
        if len(returns) < 50:
            return
        
        # 离散化为3态：下跌(< -1%) / 盘整(-1%~1%) / 上涨(> 1%)
        discretized = np.zeros(len(returns), dtype=int)
        discretized[returns < -1.0] = 0       # 下跌
        discretized[(returns >= -1.0) & (returns <= 1.0)] = 1  # 盘整
        discretized[returns > 1.0] = 2         # 上涨
        
        # 转移计数矩阵
        trans_mat = np.zeros((3, 3))
        for t in range(len(discretized) - 1):
            trans_mat[discretized[t], discretized[t+1]] += 1
        
        # 归一化为概率；空行用均匀分布，避免 [0,0,0]
        row_sums = trans_mat.sum(axis=1, keepdims=True)
        self.transition_matrix = np.divide(
            trans_mat, row_sums, out=np.full_like(trans_mat, 1 / 3),
            where=row_sums != 0)
        
        # 稳态分布（特征向量法）
        eigvals, eigvecs = np.linalg.eig(self.transition_matrix.T)
        idx = np.argmin(np.abs(eigvals - 1))
        steady = np.real(eigvecs[:, idx])
        self.steady_state = steady / steady.sum()

    def next_state_prob(self, current_return: float) -> dict:
        """给定当前收益率，预测下一日状态概率"""
        if self.transition_matrix is None:
            return {}
        if current_return < -1.0:
            curr = 0
        elif current_return > 1.0:
            curr = 2
        else:
            curr = 1
        probs = self.transition_matrix[curr]
        return {self.states[i]: float(probs[i]) for i in range(len(self.states))}

    def get_persistence(self) -> float:
        """市场持续性：对角线均值（越高越趋势化）"""
        if self.transition_matrix is None:
            return 0.5
        return float(np.trace(self.transition_matrix) / 3)


class MomentumAnalyzer:
    """多周期动量分析"""
    
    @staticmethod
    def compute(kline_df: pd.DataFrame) -> dict:
        df = kline_df.sort_values("trade_date")
        if len(df) < 5:
            return {}
        close = df["close"].values
        ret_5d = (close[-1] / close[-5] - 1) * 100 if len(close) >= 5 else 0
        ret_20d = (close[-1] / close[-20] - 1) * 100 if len(close) >= 20 else 0
        ret_60d = (close[-1] / close[-60] - 1) * 100 if len(close) >= 60 else 0
        
        # 均线排列
        ma5 = np.mean(close[-5:]) if len(close) >= 5 else 0
        ma20 = np.mean(close[-20:]) if len(close) >= 20 else 0
        ma60 = np.mean(close[-60:]) if len(close) >= 60 else 0
        
        # 判断趋势
        if ma5 > ma20 > ma60:
            trend = "多头排列 📈"
        elif ma5 < ma20 < ma60:
            trend = "空头排列 📉"
        else:
            trend = "均线交织 ⚡"
        
        # 动量强度
        strength = (ret_5d * 0.5 + ret_20d * 0.3 + ret_60d * 0.2) if any([ret_5d, ret_20d, ret_60d]) else 0
        
        return {
            "ret_5d": round(ret_5d, 2),
            "ret_20d": round(ret_20d, 2),
            "ret_60d": round(ret_60d, 2),
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "trend": trend,
            "strength": round(strength, 2),
            "signal": "买入 🟢" if strength > 2 else "卖出 🔴" if strength < -2 else "持有 ⚪"
        }


class PortfolioAnalyzer:
    """组合分析"""
    
    @staticmethod
    def summary(qdf: pd.DataFrame) -> dict:
        """组合整体统计"""
        if qdf.empty:
            return {}
        up = sum(1 for _, r in qdf.iterrows() if str(r.get("change_pct","0%")).startswith("+"))
        down = len(qdf) - up
        hold = int(qdf["is_holding"].sum())
        hold_df = qdf[qdf["is_holding"]==1]
        hold_pnl = 0
        if not hold_df.empty:
            for _, r in hold_df.iterrows():
                chg = str(r.get("change_pct","0%")).replace("%","")
                try: hold_pnl += float(chg)
                except (ValueError, TypeError):  # 单只涨跌幅解析失败则跳过
                    pass
        return {
            "total": len(qdf), "up": up, "down": down, "hold": hold,
            "hold_pnl": round(hold_pnl, 2),
            "up_ratio": round(up/len(qdf)*100, 1) if len(qdf) > 0 else 0
        }
    
    @staticmethod
    def correlation_matrix(kline_dict: dict) -> Optional[pd.DataFrame]:
        """多只股票收益率相关性矩阵"""
        series = []
        for code, df in kline_dict.items():
            if df is not None and len(df) > 20:
                s = df.sort_values("trade_date").set_index("trade_date")["close"].pct_change() * 100
                s.name = code
                series.append(s)
        if len(series) < 2:
            return None
        return pd.concat(series, axis=1).corr()
