"""
Unified Terminal Test Runner for FinTech Ingestion Pipeline & ScamShield Agent.
Executes the master verification test suite (test_pipeline.py).
"""

import sys
import unittest


def main():
    print("=" * 85)
    print("      FINTECH TRACK AGENT MASTER VERIFICATION TEST SUITE      ")
    print("=" * 85)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("test_pipeline")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 85)
    if result.wasSuccessful():
        print(f"  SUCCESS: ALL {result.testsRun} TESTS PASSED CLEANLY!")
    else:
        print(f"  FAILURE: {len(result.failures)} FAILURES AND {len(result.errors)} ERRORS DETECTED.")
    print("=" * 85 + "\n")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
