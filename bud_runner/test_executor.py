"""
TestExecutor - Discovers and runs test cases from test lists.

Handles:
- Importing test case lists from module paths
- Running tests and collecting results
- Error handling and continue-on-error support
"""

import importlib
import sys
from pathlib import Path
from typing import Any, List, Type, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TestRunResult:
    """Result of running a test case."""
    test_class: str
    passed: bool
    method_results: List[Any] = field(default_factory=list)
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    bloom_tc_id: Optional[str] = None

    def to_dict(self):
        return {
            "test_class": self.test_class,
            "passed": self.passed,
            "method_results": [
                r.to_dict() if hasattr(r, "to_dict") else r
                for r in self.method_results
            ],
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "bloom_tc_id": self.bloom_tc_id,
        }


class TestExecutor:
    """
    Executes test cases from test case lists.
    
    Usage:
        executor = TestExecutor()
        results = executor.run_test_list("Bud_Test_Suite.HIL_TEST_CASES")
    """

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize the test executor.
        
        Args:
            base_path: Base path to add to sys.path for imports.
        """
        self._base_path = base_path
        if base_path and base_path not in sys.path:
            sys.path.insert(0, base_path)

    def load_test_list(self, test_case_list: str) -> List[Type]:
        """
        Load test classes from a test case list module path.
        
        Args:
            test_case_list: Module path like "Bud_Test_Suite.HIL_TEST_CASES"
        
        Returns:
            List of test classes.
        """
        # Split into module and attribute
        parts = test_case_list.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid test case list format: {test_case_list}. "
                "Expected format: module.ATTRIBUTE"
            )
        
        module_name, list_name = parts
        
        # Import the module
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            raise ImportError(f"Cannot import module '{module_name}': {e}")
        
        # Get the test list
        if not hasattr(module, list_name):
            raise AttributeError(
                f"Module '{module_name}' has no attribute '{list_name}'"
            )
        
        test_list = getattr(module, list_name)
        
        if not isinstance(test_list, (list, tuple)):
            raise TypeError(
                f"'{list_name}' is not a list/tuple, got {type(test_list)}"
            )
        
        # Load each test class
        test_classes = []
        for test_path in test_list:
            test_class = self._load_test_class(test_path)
            if test_class:
                test_classes.append(test_class)
        
        return test_classes

    def _load_test_class(self, test_path: str) -> Optional[Type]:
        """
        Load a single test class from a module.class path.
        
        Args:
            test_path: Path like "BigPack_voltage_test.VoltageTest"
        
        Returns:
            Test class or None if not found.
        """
        parts = test_path.rsplit(".", 1)
        if len(parts) != 2:
            print(f"Warning: Invalid test path format: {test_path}")
            return None
        
        module_name, class_name = parts
        
        try:
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            print(f"Warning: Cannot load test '{test_path}': {e}")
            return None

    def run_test_list(
        self,
        test_case_list: str,
        continue_on_error: bool = True,
    ) -> List[TestRunResult]:
        """
        Run all tests from a test case list.
        
        Args:
            test_case_list: Module path to the test list.
            continue_on_error: Continue with next test after failure.
        
        Returns:
            List of TestRunResult for each test class.
        """
        test_classes = self.load_test_list(test_case_list)
        results = []
        
        for test_class in test_classes:
            result = self.run_test_class(test_class)
            results.append(result)
            
            if not result.passed and not continue_on_error:
                break
        
        return results

    def run_test_class(self, test_class: Type) -> TestRunResult:
        """
        Run a single test class.
        
        Args:
            test_class: The test class to run.
        
        Returns:
            TestRunResult with execution details.
        """
        import time
        
        result = TestRunResult(
            test_class=test_class.__name__,
            passed=True,
            start_time=datetime.now(),
        )
        
        bloom_tc_id = None
        bloom_meta = getattr(test_class, "bloom_metadata", None)
        if bloom_meta and hasattr(bloom_meta, "get_full_tc_id"):
            bloom_tc_id = bloom_meta.get_full_tc_id()
        result.bloom_tc_id = bloom_tc_id
        
        start_time = time.time()
        
        try:
            # Instantiate and run the test
            test_instance = test_class()
            
            # Set up logging if available
            import logging
            if hasattr(test_instance, "set_loglevel"):
                test_instance.set_loglevel(logging.INFO)
            
            # Run the test
            passed = test_instance.run()
            result.passed = passed
            
            # Collect method results
            if hasattr(test_instance, "get_results"):
                result.method_results = test_instance.get_results()
            
        except Exception as e:
            result.passed = False
            result.error_message = str(e)
            import traceback
            print(f"Error running {test_class.__name__}: {e}")
            traceback.print_exc()
        
        result.end_time = datetime.now()
        result.duration_seconds = time.time() - start_time
        
        return result

    def run_single_test(
        self,
        test_path: str,
    ) -> TestRunResult:
        """
        Run a single test by module.class path.
        
        Args:
            test_path: Path like "BigPack_voltage_test.VoltageTest"
        
        Returns:
            TestRunResult with execution details.
        """
        test_class = self._load_test_class(test_path)
        if not test_class:
            return TestRunResult(
                test_class=test_path,
                passed=False,
                error_message=f"Could not load test class: {test_path}",
            )
        
        return self.run_test_class(test_class)
