import pandas as pd


class RollingCorrelationFilter:
    """
    فلتر يمنع فتح صفقات جديدة على أصول
    شديدة الارتباط مع صفقات مفتوحة بالفعل.
    """

    def __init__(
        self,
        window: int = 100,
        threshold: float = 0.75,
    ):
        self.window = window
        self.threshold = threshold

    # ---------------------------------------------------------

    def calculate_matrix(
        self,
        prices_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        يحسب مصفوفة الارتباط اعتماداً على العوائد
        وليس الأسعار الخام.
        """

        returns = prices_df.pct_change().dropna()

        returns = returns.tail(self.window)

        return returns.corr()

    # ---------------------------------------------------------

    def is_allowed(
        self,
        symbol: str,
        open_symbols: list,
        correlation_matrix: pd.DataFrame,
    ):
        """
        يرجع:
            True إذا كانت العملة مسموحة.

            False إذا كان الارتباط مرتفعاً.
        """

        if not open_symbols:
            return True, "OK"

        for other in open_symbols:

            if (
                symbol not in correlation_matrix.columns
                or other not in correlation_matrix.columns
            ):
                continue

            corr = correlation_matrix.loc[symbol, other]

            if corr >= self.threshold:

                return (
                    False,
                    f"High Correlation ({corr:.2f}) with {other}",
                )

        return True, "OK"

    # ---------------------------------------------------------

    def correlation_value(
        self,
        symbol_a,
        symbol_b,
        matrix,
    ):
        """
        إرجاع قيمة الارتباط فقط.
        """

        if (
            symbol_a not in matrix.columns
            or symbol_b not in matrix.columns
        ):
            return None

        return matrix.loc[symbol_a, symbol_b]
