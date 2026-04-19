"""
JUnitReporter - Generate JUnit XML reports for CI/CD integration.

Creates JUnit XML format compatible with:
- GitHub Actions
- GitLab CI
- Jenkins
- Other CI/CD systems
"""

from typing import List, Any, Optional, Dict
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from datetime import datetime


class JUnitReporter:
    """
    Generates JUnit XML reports from test results.
    
    Usage:
        reporter = JUnitReporter()
        xml = reporter.generate(results)
        
        with open("report_junit.xml", "w") as f:
            f.write(xml)
    """

    def __init__(self, suite_name: str = "BudTestSuite"):
        """
        Initialize the reporter.
        
        Args:
            suite_name: Name for the test suite in the report.
        """
        self._suite_name = suite_name

    def generate(self, results: List[Any], warnings: Optional[List[str]] = None) -> str:
        """
        Generate JUnit XML from test results.
        
        Args:
            results: List of TestRunResult or similar objects.
            warnings: Optional list of strings (e.g. ALM sync issues) to include.
        
        Returns:
            JUnit XML string.
        """
        # Create root testsuites element
        testsuites = Element("testsuites")
        testsuites.set("name", self._suite_name)
        testsuites.set("tests", str(self._count_tests(results)))
        testsuites.set("failures", str(self._count_failures(results)))
        testsuites.set("errors", "0")
        testsuites.set("time", str(self._total_time(results)))

        # INJECT WARNINGS (ALM Sync Mismatches, etc)
        if warnings:
            system_err = SubElement(testsuites, "system-err")
            system_err.text = "\n".join(warnings)

        for result in results:
            testsuite = self._create_testsuite(result)
            testsuites.append(testsuite)

        xml_str = tostring(testsuites, encoding="unicode")
        return minidom.parseString(xml_str).toprettyxml(indent="  ")

    def generate_single(self, result: Any) -> str:
        """
        Generate JUnit XML for a single test class result.
        
        Args:
            result: TestRunResult or similar object.
        
        Returns:
            JUnit XML string.
        """
        testsuite = self._create_testsuite(result)
        xml_str = tostring(testsuite, encoding="unicode")
        return minidom.parseString(xml_str).toprettyxml(indent="  ")

    def _create_testsuite(self, result: Any) -> Element:
        """Create a testsuite element from a test result."""
        testsuite = Element("testsuite")
        
        # Get test class name
        if hasattr(result, "test_class"):
            name = result.test_class
        else:
            name = str(result.get("test_class", "UnknownTest"))
        
        testsuite.set("name", name)
        
        # Get method results
        method_results = []
        if hasattr(result, "method_results"):
            method_results = result.method_results
        elif isinstance(result, dict):
            method_results = result.get("method_results", [])
        
        testsuite.set("tests", str(len(method_results)))
        testsuite.set("failures", str(sum(1 for r in method_results if not self._is_passed(r))))
        testsuite.set("errors", "0")
        
        # Duration
        duration = 0.0
        if hasattr(result, "duration_seconds"):
            duration = result.duration_seconds
        elif isinstance(result, dict):
            duration = result.get("duration_seconds", 0.0)
        testsuite.set("time", str(duration))
        
        # Timestamp
        start_time = None
        if hasattr(result, "start_time"):
            start_time = result.start_time
        elif isinstance(result, dict):
            start_time = result.get("start_time")
        
        if start_time:
            if isinstance(start_time, str):
                testsuite.set("timestamp", start_time)
            elif isinstance(start_time, datetime):
                testsuite.set("timestamp", start_time.isoformat())

        # Add test cases
        for method_result in method_results:
            testcase = self._create_testcase(method_result, name)
            testsuite.append(testcase)

        # If no method results but there was an error
        if not method_results:
            error_msg = None
            if hasattr(result, "error_message"):
                error_msg = result.error_message
            elif isinstance(result, dict):
                error_msg = result.get("error_message")
            
            if error_msg:
                testcase = SubElement(testsuite, "testcase")
                testcase.set("name", "setup")
                testcase.set("classname", name)
                testcase.set("time", "0")
                
                error = SubElement(testcase, "error")
                error.set("message", error_msg)
                error.text = error_msg

        return testsuite

    def _create_testcase(self, method_result: Any, classname: str) -> Element:
        """Create a testcase element from a method result."""
        testcase = Element("testcase")
        
        # Method name
        if hasattr(method_result, "method_name"):
            name = method_result.method_name
        elif isinstance(method_result, dict):
            name = method_result.get("method_name", "unknown")
        else:
            name = "unknown"
        
        testcase.set("name", name)
        testcase.set("classname", classname)
        
        # Duration
        duration = 0.0
        if hasattr(method_result, "duration_seconds"):
            duration = method_result.duration_seconds
        elif isinstance(method_result, dict):
            duration = method_result.get("duration_seconds", 0.0)
        testcase.set("time", str(duration))
        
        # Check for failure
        passed = self._is_passed(method_result)
        
        if not passed:
            failure = SubElement(testcase, "failure")
            
            # Get error message
            error_msg = "Test failed"
            if hasattr(method_result, "error_message") and method_result.error_message:
                error_msg = method_result.error_message
            elif isinstance(method_result, dict):
                error_msg = method_result.get("error_message", "Test failed")
            
            failure.set("message", error_msg)
            
            # Get traceback
            tb = None
            if hasattr(method_result, "traceback"):
                tb = method_result.traceback
            elif isinstance(method_result, dict):
                tb = method_result.get("traceback")
            
            if tb:
                failure.text = tb
            else:
                failure.text = error_msg

        return testcase

    def _is_passed(self, result: Any) -> bool:
        """Check if a result indicates pass."""
        if hasattr(result, "passed"):
            return result.passed
        elif isinstance(result, dict):
            return result.get("passed", False)
        return False

    def _count_tests(self, results: List[Any]) -> int:
        """Count total tests across all results."""
        total = 0
        for result in results:
            if hasattr(result, "method_results"):
                total += len(result.method_results)
            elif isinstance(result, dict):
                total += len(result.get("method_results", []))
            else:
                total += 1
        return total

    def _count_failures(self, results: List[Any]) -> int:
        """Count total failures across all results."""
        failures = 0
        for result in results:
            method_results = []
            if hasattr(result, "method_results"):
                method_results = result.method_results
            elif isinstance(result, dict):
                method_results = result.get("method_results", [])
            
            for mr in method_results:
                if not self._is_passed(mr):
                    failures += 1
        
        return failures

    def _total_time(self, results: List[Any]) -> float:
        """Calculate total time across all results."""
        total = 0.0
        for result in results:
            if hasattr(result, "duration_seconds"):
                total += result.duration_seconds
            elif isinstance(result, dict):
                total += result.get("duration_seconds", 0.0)
        return total
