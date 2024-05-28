#!/usr/bin/env python3
# Version 3.1

import sys
import logging


class Functions:

    # Exception safe max and min (attention, not working with dictionaries)
    # another option: res = [i for i in test_list if i is not None]

    def _max(self, x):
        try:
            return max(x)
        except Exception:
            return None

    def _min(self, x):
        try:
            return min(x)
        except Exception:
            return None

    # Interpolate f(x) if given lists Y = f(X)

    def _interpolate(self, X, Y, x):
        if len(X) == len(Y):
            _len = len(X)
            if x <= X[0]:
                return Y[0]
            elif x >= X[_len - 1]:
                return Y[_len - 1]
            else:
                for i in range(_len - 1):
                    if x <= X[i + 1]:
                        return Y[i] + (Y[i + 1] - Y[i]) / (X[i + 1] - X[i]) * (x - X[i])
        else:
            logging.error("Both lists must have the same length. Exiting.")
            sys.exit()


################
# test program #
################


def main():
    import settings as s

    fn = Functions()
    for x in range(0, 251):
        print(
            "%.2f %.0f"
            % (
                x / 100.0,
                s.MAX_CHARGE_CURRENT
                * fn._interpolate(
                    s.CELL_CHARGE_LIMITING_VOLTAGE,
                    s.CELL_CHARGE_LIMITED_CURRENT,
                    x / 100.0,
                ),
            )
        )


if __name__ == "__main__":
    main()
