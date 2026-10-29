r"""Red-pen catalog of this project: failure patterns met here, with WHY and HOW TO FIX.

Checked before the harness catalog (engine/errors.py of the plugin). Harness updates never
overwrite this file. Add an entry each time a failure printed "No catalog entry":

    Entry("stock-quant-negative",
          r"You cannot validate .* negative quantity of (\S+)",
          "Product {1} has no stock in the test data.",
          "Create a stock.quant for {1} in the test setUpClass."),
"""

from errors import Entry  # noqa: F401  (used by the entries below)

PROJECT_CATALOG = [
]
