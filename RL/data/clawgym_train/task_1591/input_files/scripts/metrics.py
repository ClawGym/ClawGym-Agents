from math import sqrt

def annualized_sharpe(avg_daily_return: float, std_daily_return: float) -> float:
    """
    Compute annualized Sharpe ratio from average and standard deviation of daily returns.
    Formula: Sharpe = sqrt(252) * avg_daily_return / std_daily_return.
    If std_daily_return <= 0, return 0.0 to avoid division by zero.
    """
    if std_daily_return <= 0:
        return 0.0
    return sqrt(252.0) * (avg_daily_return / std_daily_return)


def cagr_from_avg_daily(avg_daily_return: float) -> float:
    """
    Approximate annualized return (CAGR) from average daily return assuming 252 trading days/year.
    Formula: CAGR = (1 + avg_daily_return) ** 252 - 1.
    """
    return (1.0 + avg_daily_return) ** 252.0 - 1.0


def calmar_ratio(cagr: float, max_drawdown: float) -> float:
    """
    Calmar ratio defined as CAGR / Max Drawdown. If max_drawdown <= 0, return 0.0.
    Max drawdown is expected as a positive fraction (e.g., 0.22 for 22%).
    """
    if max_drawdown <= 0:
        return 0.0
    return cagr / max_drawdown
