"""
UC2 Grid Utilities

This module provides utility functions for creating UC2 cube assemblies
in grid patterns. It includes helper functions for common operations.
"""

import os
import csv
from PyInventor import iAssembly

def create_uc2_assembly_from_csv(csv_file_path, assembly_name='UC2_Assembly.iam', 
                                assembly_path='', grid_spacing=(50.0, 50.0, 55.0)):
    """
    Create UC2 assembly from a CSV file containing component definitions.
    
    CSV format:
    name, file_path, grid_x, grid_y, grid_z, rot_x, rot_y, rot_z
    
    Args:
        csv_file_path: Path to CSV file with component definitions
        assembly_name: Name for the assembly file
        assembly_path: Directory for the assembly file
        grid_spacing: (x, y, z) spacing for grid in mm
        
    Returns:
        iAssembly object
    """
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"CSV file not found: {csv_file_path}")
    
    # Create assembly
    assembly = iAssembly(
        path=assembly_path,
        prefix=assembly_name,
        units='metric',
        overwrite=True
    )
    
    # Set grid spacing
    assembly.set_grid_spacing(*grid_spacing)
    
    # Read CSV and create component table
    components = []
    with open(csv_file_path, 'r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            component = {
                'name': row['name'],
                'file': row['file_path'],
                'grid_pos': (int(row['grid_x']), int(row['grid_y']), int(row['grid_z'])),
                'rotation': (float(row.get('rot_x', 0)), 
                           float(row.get('rot_y', 0)), 
                           float(row.get('rot_z', 0)))
            }
            components.append(component)
    
    # Place components
    placed_components = assembly.create_uc2_grid_from_table(components)
    
    # Save assembly
    assembly.save()
    
    print(f"Created UC2 assembly with {len(placed_components)} components from {csv_file_path}")
    
    return assembly

def generate_sample_csv(csv_path='uc2_components.csv'):
    """
    Generate a sample CSV file for UC2 component definitions.
    
    Args:
        csv_path: Path where to save the sample CSV
    """
    sample_data = [
        ['name', 'file_path', 'grid_x', 'grid_y', 'grid_z', 'rot_x', 'rot_y', 'rot_z'],
        ['Lens_Origin', 'C:/UC2/Assembly_cube_lens.iam', '0', '0', '0', '0', '0', '0'],
        ['Mirror_50mm', 'C:/UC2/Assembly_cube_mirror.iam', '1', '0', '0', '0', '90', '0'],
        ['Lens_Y50', 'C:/UC2/Assembly_cube_lens.iam', '0', '1', '0', '0', '0', '0'],
        ['Mirror_Corner', 'C:/UC2/Assembly_cube_mirror.iam', '1', '1', '0', '0', '45', '0'],
        ['BeamSplitter_Center', 'C:/UC2/Assembly_cube_beamsplitter.iam', '0', '0', '1', '0', '0', '0']
    ]
    
    with open(csv_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(sample_data)
    
    print(f"Sample CSV created at: {csv_path}")

def create_rectangular_grid(width, height, layers=1, component_file='', 
                          assembly_name='UC2_Grid.iam', assembly_path=''):
    """
    Create a rectangular grid of identical UC2 components.
    
    Args:
        width: Number of components in X direction
        height: Number of components in Y direction  
        layers: Number of components in Z direction
        component_file: Path to the component file to replicate
        assembly_name: Name for the assembly
        assembly_path: Directory for the assembly
        
    Returns:
        iAssembly object
    """
    assembly = iAssembly(
        path=assembly_path,
        prefix=assembly_name,
        units='metric',
        overwrite=True
    )
    
    assembly.set_grid_spacing(50.0, 50.0, 55.0)
    
    components = []
    for z in range(layers):
        for y in range(height):
            for x in range(width):
                component = {
                    'name': f'Component_{x}_{y}_{z}',
                    'file': component_file,
                    'grid_pos': (x, y, z),
                    'rotation': (0, 0, 0)
                }
                components.append(component)
    
    placed_components = assembly.create_uc2_grid_from_table(components)
    assembly.save()
    
    print(f"Created {width}x{height}x{layers} grid with {len(placed_components)} components")
    
    return assembly

def create_alternating_pattern(width, height, component_files, 
                             assembly_name='UC2_Pattern.iam', assembly_path=''):
    """
    Create an alternating pattern of different UC2 components.
    
    Args:
        width: Grid width
        height: Grid height
        component_files: List of component file paths to alternate between
        assembly_name: Assembly filename
        assembly_path: Assembly directory
        
    Returns:
        iAssembly object
    """
    assembly = iAssembly(
        path=assembly_path,
        prefix=assembly_name,
        units='metric',
        overwrite=True
    )
    
    assembly.set_grid_spacing(50.0, 50.0, 55.0)
    
    components = []
    for y in range(height):
        for x in range(width):
            # Checkerboard pattern
            component_index = (x + y) % len(component_files)
            
            component = {
                'name': f'Component_{x}_{y}',
                'file': component_files[component_index],
                'grid_pos': (x, y, 0),
                'rotation': (0, 0, 0)
            }
            components.append(component)
    
    placed_components = assembly.create_uc2_grid_from_table(components)
    assembly.save()
    
    print(f"Created alternating pattern with {len(placed_components)} components")
    
    return assembly

def validate_component_files(component_table):
    """
    Validate that all component files in a table exist.
    
    Args:
        component_table: List of component dictionaries
        
    Returns:
        (valid_components, missing_files)
    """
    valid_components = []
    missing_files = []
    
    for component in component_table:
        file_path = component['file']
        if os.path.exists(file_path):
            valid_components.append(component)
        else:
            missing_files.append(file_path)
    
    return valid_components, missing_files

# Example usage functions
def demo_csv_workflow():
    """Demonstrate CSV-based workflow."""
    print("=== CSV Workflow Demo ===")
    
    # Generate sample CSV
    csv_file = 'demo_uc2_components.csv'
    generate_sample_csv(csv_file)
    
    # NOTE: In a real scenario, user would edit the CSV file
    # to point to their actual component files
    
    print(f"1. Sample CSV generated: {csv_file}")
    print("2. Edit the CSV file to point to your UC2 component files")
    print("3. Run create_uc2_assembly_from_csv() to create the assembly")

def demo_grid_patterns():
    """Demonstrate different grid patterns."""
    print("=== Grid Pattern Demo ===")
    
    # Example component files (adjust paths as needed)
    lens_file = 'C:/UC2/Assembly_cube_lens.iam'
    mirror_file = 'C:/UC2/Assembly_cube_mirror.iam'
    
    print("Available pattern functions:")
    print("1. create_rectangular_grid() - Creates uniform grid")
    print("2. create_alternating_pattern() - Creates checkerboard pattern")
    print("3. create_uc2_assembly_from_csv() - Creates from CSV definition")

if __name__ == "__main__":
    print("UC2 Grid Utilities")
    print("This module provides functions for creating UC2 assemblies.")
    print("Import this module and use the functions in your scripts.")
    print()
    
    demo_csv_workflow()
    print()
    demo_grid_patterns()