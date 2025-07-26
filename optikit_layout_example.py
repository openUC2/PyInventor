#!/usr/bin/env python3
"""
Example script demonstrating how to load UC2 components from optikit-layout.json format.

This example shows how to use the new load_from_optikit_layout() method to create
assemblies from the standardized OpenUC2 OptiKit layout format.
"""

from PyInventor import iAssembly

def main():
    """
    Example: Load and create UC2 assembly from optikit-layout.json
    """
    # Create new assembly with UC2 grid settings
    assembly = iAssembly('UC2_OptiKit_Assembly.iam', units='metric')
    
    # Set standard UC2 grid spacing (50x50x55mm)
    assembly.set_grid_spacing(50.0, 50.0, 55.0)
    
    # Load components from optikit-layout.json format
    try:
        placed_components = assembly.load_from_optikit_layout('optikit-layout.json')
        
        print(f"Successfully placed {len(placed_components)} components:")
        for i, comp in enumerate(placed_components):
            print(f"  {i+1}. {comp.Name}")
        
        # Save the assembly
        assembly.save()
        print("\nAssembly saved successfully!")
        
    except Exception as e:
        print(f"Error: {str(e)}")
    
    finally:
        # Close the assembly
        assembly.close()

if __name__ == "__main__":
    main()