"""
Simple UC2 Grid Script - Exact Issue Implementation

This script implements the exact example from GitHub issue #3:
- Assembly_cube_lens.iam at 0,0,0 at orientation 0,0
- Assembly_cube_mirror.iam at 50,0,0 at angle 0,90
- 50x50x55mm grid spacing

This is the minimal script that solves the stated problem.
"""

from PyInventor import iAssembly

def create_uc2_issue_example():
    """Create the exact UC2 assembly described in the GitHub issue."""
    
    # Create assembly with 50x50x55mm grid
    assembly = iAssembly(
        path='',  # Use current directory, adjust as needed
        prefix='UC2_Issue_Example.iam',
        units='metric',  # Use metric for mm measurements
        overwrite=True
    )
    
    # Set the 50x50x55mm grid spacing as specified
    assembly.set_grid_spacing(x_spacing=50.0, y_spacing=50.0, z_spacing=55.0)
    
    print("Creating UC2 assembly as specified in the issue...")
    
    # Place Assembly_cube_lens.iam at 0,0,0 at orientation 0,0
    print("Placing Assembly_cube_lens.iam at 0,0,0 with orientation 0,0")
    assembly.place_component_at_grid(
        component_path='Assembly_cube_lens.iam',  # Adjust path as needed
        grid_x=0, grid_y=0, grid_z=0,
        rotation=(0, 0, 0)  # Orientation 0,0 (no rotation)
    )
    
    # Place Assembly_cube_mirror.iam at 50,0,0 at angle 0,90
    print("Placing Assembly_cube_mirror.iam at 50,0,0 with angle 0,90")
    assembly.place_component_at_grid(
        component_path='Assembly_cube_mirror.iam',  # Adjust path as needed
        grid_x=1, grid_y=0, grid_z=0,  # Grid (1,0,0) = position (50,0,0)mm
        rotation=(0, 90, 0)  # Angle 0,90 (90° rotation around Y-axis)
    )
    
    # Save the assembly
    assembly.save()
    print("UC2 assembly saved as UC2_Issue_Example.iam")
    
    return assembly

if __name__ == "__main__":
    print("UC2 Grid Assembly - Issue #3 Implementation")
    print("=" * 50)
    
    try:
        assembly = create_uc2_issue_example()
        print("\n✅ Success! UC2 assembly created exactly as specified in the issue.")
        print("\nAssembly contains:")
        print("- Assembly_cube_lens.iam at (0,0,0)mm with no rotation")
        print("- Assembly_cube_mirror.iam at (50,0,0)mm with 90° rotation")
        print("- Grid spacing: 50x50x55mm")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTo use this script:")
        print("1. Ensure Autodesk Inventor is installed")
        print("2. Update component file paths to point to your UC2 files")
        print("3. Run on Windows with PyInventor dependencies installed")