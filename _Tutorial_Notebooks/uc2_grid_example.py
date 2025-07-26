"""
UC2 Grid Assembly Example

This example demonstrates how to create complex UC2 assemblies in a 50x50x55mm grid
using the PyInventor iAssembly class.

The script shows how to:
1. Create a new assembly document
2. Set up grid spacing (50x50x55mm)
3. Place UC2 components from a table with positions and orientations
4. Save the assembly

Example usage described in the GitHub issue:
- Assembly_cube_lens.iam at (0,0,0) with orientation (0,0)
- Assembly_cube_mirror.iam at (50,0,0) with angle (0,90)
"""

import PyInventor
from PyInventor import iAssembly
import os

def create_uc2_grid_assembly():
    """Create a UC2 assembly with components placed in a grid."""
    
    # Create new assembly document
    assembly = iAssembly(
        path='C:\\UC2_Assemblies',  # Adjust path as needed
        prefix='UC2_Grid_Assembly.iam',
        units='metric',  # Use metric units for mm measurements
        overwrite=True
    )
    
    print("=== UC2 Grid Assembly Creation ===")
    print(f"Assembly created: {assembly.f_name}")
    
    # Set grid spacing (50x50x55mm as specified in the issue)
    assembly.set_grid_spacing(x_spacing=50.0, y_spacing=50.0, z_spacing=55.0)
    print(f"Grid spacing set to: {assembly.grid_spacing}")
    
    # Define UC2 component table
    # This table defines which components to place where
    uc2_components = [
        {
            'name': 'Lens_Cube_00',
            'file': 'C:\\UC2_Components\\Assembly_cube_lens.iam',  # Adjust path as needed
            'grid_pos': (0, 0, 0),  # Grid coordinates (not mm)
            'rotation': (0, 0, 0)   # No rotation (0,0 as specified)
        },
        {
            'name': 'Mirror_Cube_10', 
            'file': 'C:\\UC2_Components\\Assembly_cube_mirror.iam',  # Adjust path as needed
            'grid_pos': (1, 0, 0),  # Grid coordinates: (1*50, 0*50, 0*55) = (50,0,0)mm
            'rotation': (0, 90, 0)  # 90 degree rotation around Y axis (0,90 as specified)
        },
        {
            'name': 'Lens_Cube_01',
            'file': 'C:\\UC2_Components\\Assembly_cube_lens.iam',
            'grid_pos': (0, 1, 0),  # At (0,50,0)mm
            'rotation': (0, 0, 0)
        },
        {
            'name': 'Mirror_Cube_11',
            'file': 'C:\\UC2_Components\\Assembly_cube_mirror.iam', 
            'grid_pos': (1, 1, 0),  # At (50,50,0)mm
            'rotation': (0, 45, 0)  # 45 degree rotation
        },
        {
            'name': 'Lens_Cube_Layer2',
            'file': 'C:\\UC2_Components\\Assembly_cube_lens.iam',
            'grid_pos': (0, 0, 1),  # At (0,0,55)mm - second layer
            'rotation': (0, 0, 0)
        }
    ]
    
    print(f"\nPlacing {len(uc2_components)} UC2 components...")
    
    # Create the grid assembly from the table
    placed_components = assembly.create_uc2_grid_from_table(uc2_components)
    
    print(f"\nSuccessfully placed {len(placed_components)} components")
    
    # Save the assembly
    print("\nSaving assembly...")
    assembly.save()
    print("Assembly saved successfully!")
    
    # Fit the view to show all components
    assembly.view.Fit()
    
    return assembly, placed_components

def create_large_uc2_grid():
    """Create a larger UC2 grid assembly (5x5x2 grid)."""
    
    assembly = iAssembly(
        path='C:\\UC2_Assemblies',
        prefix='UC2_Large_Grid.iam', 
        units='metric',
        overwrite=True
    )
    
    print("=== Large UC2 Grid Assembly (5x5x2) ===")
    
    # Set standard UC2 grid spacing  
    assembly.set_grid_spacing(50.0, 50.0, 55.0)
    
    # Create a larger grid programmatically
    large_grid_components = []
    
    # Available component types
    component_types = [
        'C:\\UC2_Components\\Assembly_cube_lens.iam',
        'C:\\UC2_Components\\Assembly_cube_mirror.iam',
        'C:\\UC2_Components\\Assembly_cube_beamsplitter.iam',  # Additional components
        'C:\\UC2_Components\\Assembly_cube_empty.iam'
    ]
    
    # Create 5x5x2 grid
    for z in range(2):  # 2 layers
        for y in range(5):  # 5 rows
            for x in range(5):  # 5 columns
                # Alternate component types in a pattern
                comp_index = (x + y + z) % len(component_types)
                
                # Calculate rotation based on position
                rotation_angle = (x * 45) % 360  # Rotate based on X position
                
                component = {
                    'name': f'UC2_Component_{x}_{y}_{z}',
                    'file': component_types[comp_index],
                    'grid_pos': (x, y, z),
                    'rotation': (0, rotation_angle, 0)
                }
                
                large_grid_components.append(component)
    
    print(f"Creating grid with {len(large_grid_components)} components...")
    
    # Place all components
    placed_components = assembly.create_uc2_grid_from_table(large_grid_components)
    
    # Save the assembly
    assembly.save()
    assembly.view.Fit()
    
    print(f"Large grid assembly created with {len(placed_components)} components")
    
    return assembly

def main():
    """Main function to demonstrate UC2 grid functionality."""
    
    try:
        print("PyInventor UC2 Grid Assembly Demo")
        print("=================================")
        
        # Create basic UC2 grid as specified in the issue
        print("\n1. Creating basic UC2 grid assembly...")
        assembly, components = create_uc2_grid_assembly()
        
        print("\n2. Assembly creation complete!")
        print(f"   - Assembly file: {assembly.f_name}")
        print(f"   - Components placed: {len(components)}")
        print(f"   - Grid spacing: {assembly.grid_spacing} mm")
        
        # Optionally create a larger grid
        create_large = input("\nCreate large 5x5x2 grid? (y/n): ").lower().strip()
        if create_large == 'y':
            print("\n3. Creating large UC2 grid...")
            large_assembly = create_large_uc2_grid()
            print("Large grid assembly created!")
        
        print("\n=== Demo Complete ===")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nNote: This example requires:")
        print("1. Windows operating system")
        print("2. Autodesk Inventor installed")
        print("3. UC2 component files (.iam) in the specified directories")
        print("4. Proper file paths for your system")

if __name__ == "__main__":
    main()