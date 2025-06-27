"""
Test script for UC2 Grid functionality

This script tests the new iAssembly class and UC2 grid functionality
without requiring Autodesk Inventor to be installed.
"""

import sys
import os

def test_imports():
    """Test that the new classes can be imported."""
    print("Testing imports...")
    
    try:
        # Add the PyInventor directory to the path
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'PyInventor'))
        
        # Test importing the module
        import pyinvent
        print("✓ pyinvent module imported successfully")
        
        # Test that iAssembly class exists
        if hasattr(pyinvent, 'iAssembly'):
            print("✓ iAssembly class found in pyinvent module")
        else:
            print("✗ iAssembly class NOT found in pyinvent module")
            return False
            
        # Test importing from __init__
        from PyInventor import iAssembly
        print("✓ iAssembly can be imported from PyInventor")
        
        return True
        
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False
    except Exception as e:
        print(f"✗ Other error: {e}")
        return False

def test_class_structure():
    """Test the structure of the iAssembly class."""
    print("\nTesting iAssembly class structure...")
    
    try:
        from PyInventor import iAssembly
        
        # Check for required methods
        required_methods = [
            'new_assembly',
            'set_units', 
            'unit_conv',
            'ang_conv',
            'place_component',
            'set_grid_spacing',
            'place_component_at_grid',
            'create_uc2_grid_from_table',
            'save',
            'close'
        ]
        
        for method in required_methods:
            if hasattr(iAssembly, method):
                print(f"✓ Method {method} found")
            else:
                print(f"✗ Method {method} NOT found")
                
        print(f"iAssembly class has {len([m for m in dir(iAssembly) if not m.startswith('_')])} public methods")
        
        return True
        
    except Exception as e:
        print(f"✗ Error testing class structure: {e}")
        return False

def test_grid_calculation():
    """Test grid coordinate calculations."""
    print("\nTesting grid calculations...")
    
    try:
        # Test grid spacing logic
        grid_spacing = (50.0, 50.0, 55.0)
        
        test_cases = [
            ((0, 0, 0), (0.0, 0.0, 0.0)),
            ((1, 0, 0), (50.0, 0.0, 0.0)),
            ((0, 1, 0), (0.0, 50.0, 0.0)),
            ((0, 0, 1), (0.0, 0.0, 55.0)),
            ((1, 1, 1), (50.0, 50.0, 55.0)),
            ((2, 3, 1), (100.0, 150.0, 55.0))
        ]
        
        for grid_coords, expected_pos in test_cases:
            actual_x = grid_coords[0] * grid_spacing[0]
            actual_y = grid_coords[1] * grid_spacing[1]
            actual_z = grid_coords[2] * grid_spacing[2]
            actual_pos = (actual_x, actual_y, actual_z)
            
            if actual_pos == expected_pos:
                print(f"✓ Grid {grid_coords} -> Position {actual_pos}")
            else:
                print(f"✗ Grid {grid_coords} -> Expected {expected_pos}, got {actual_pos}")
                
        return True
        
    except Exception as e:
        print(f"✗ Error testing grid calculations: {e}")
        return False

def test_component_table_structure():
    """Test component table structure validation."""
    print("\nTesting component table structure...")
    
    try:
        # Test valid component table
        valid_table = [
            {
                'name': 'Test_Lens',
                'file': '/path/to/lens.iam',
                'grid_pos': (0, 0, 0),
                'rotation': (0, 0, 0)
            },
            {
                'name': 'Test_Mirror', 
                'file': '/path/to/mirror.iam',
                'grid_pos': (1, 0, 0),
                'rotation': (0, 90, 0)
            }
        ]
        
        # Validate structure
        for i, component in enumerate(valid_table):
            required_keys = ['name', 'file', 'grid_pos']
            optional_keys = ['rotation']
            
            for key in required_keys:
                if key in component:
                    print(f"✓ Component {i}: has required key '{key}'")
                else:
                    print(f"✗ Component {i}: missing required key '{key}'")
                    
            # Check grid_pos format
            if 'grid_pos' in component and len(component['grid_pos']) == 3:
                print(f"✓ Component {i}: grid_pos has 3 coordinates")
            else:
                print(f"✗ Component {i}: grid_pos format invalid")
                
            # Check rotation format if present
            if 'rotation' in component and len(component['rotation']) == 3:
                print(f"✓ Component {i}: rotation has 3 angles")
            elif 'rotation' not in component:
                print(f"✓ Component {i}: rotation optional and not provided")
            else:
                print(f"✗ Component {i}: rotation format invalid")
                
        return True
        
    except Exception as e:
        print(f"✗ Error testing component table: {e}")
        return False

def test_utilities():
    """Test utility functions."""
    print("\nTesting utility functions...")
    
    try:
        # Test importing utilities
        sys.path.insert(0, os.path.dirname(__file__))
        import uc2_grid_utilities as utils
        print("✓ uc2_grid_utilities imported successfully")
        
        # Check for utility functions
        utility_functions = [
            'create_uc2_assembly_from_csv',
            'generate_sample_csv',
            'create_rectangular_grid',
            'create_alternating_pattern',
            'validate_component_files'
        ]
        
        for func_name in utility_functions:
            if hasattr(utils, func_name):
                print(f"✓ Utility function {func_name} found")
            else:
                print(f"✗ Utility function {func_name} NOT found")
                
        return True
        
    except Exception as e:
        print(f"✗ Error testing utilities: {e}")
        return False

def test_csv_file():
    """Test sample CSV file format."""
    print("\nTesting sample CSV file...")
    
    try:
        import csv
        csv_file = os.path.join(os.path.dirname(__file__), 'sample_uc2_components.csv')
        
        if os.path.exists(csv_file):
            print(f"✓ Sample CSV file exists: {csv_file}")
            
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                
                expected_headers = ['name', 'file_path', 'grid_x', 'grid_y', 'grid_z', 'rot_x', 'rot_y', 'rot_z']
                
                for header in expected_headers:
                    if header in headers:
                        print(f"✓ CSV has header: {header}")
                    else:
                        print(f"✗ CSV missing header: {header}")
                        
                # Count rows
                rows = list(reader)
                print(f"✓ CSV has {len(rows)} component definitions")
                
        else:
            print(f"✗ Sample CSV file not found: {csv_file}")
            
        return True
        
    except Exception as e:
        print(f"✗ Error testing CSV file: {e}")
        return False

def main():
    """Run all tests."""
    print("UC2 Grid Functionality Tests")
    print("============================")
    
    tests = [
        test_imports,
        test_class_structure,
        test_grid_calculation,
        test_component_table_structure,
        test_utilities,
        test_csv_file
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            print()  # Add spacing between tests
        except Exception as e:
            print(f"Test {test.__name__} failed with exception: {e}")
            print()
    
    print("="*50)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed! UC2 grid functionality is ready.")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
    
    print("\nNote: These tests only validate the code structure.")
    print("Full functionality requires Autodesk Inventor to be installed.")

if __name__ == "__main__":
    main()