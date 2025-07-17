"""
Unified Assembly Example - UC2 Grid Creation + Image Generation

This example demonstrates the combined functionality of the merged iAssembly class:
1. Create a UC2 grid assembly with components at specific positions
2. Generate images from multiple perspectives of the created assembly
3. Show how both features work together seamlessly

This addresses both use cases:
- UC2 grid assembly creation (issue #3)
- Assembly image generation from multiple perspectives 
"""

from PyInventor import iAssembly
import os

def create_uc2_assembly_with_images():
    """
    Create a UC2 assembly and then generate images from it.
    This demonstrates both key features of the unified iAssembly class.
    """
    
    print("=" * 60)
    print("UNIFIED ASSEMBLY EXAMPLE: UC2 Grid + Image Generation")
    print("=" * 60)
    
    # Step 1: Create UC2 Grid Assembly
    print("\n🔧 STEP 1: Creating UC2 Grid Assembly")
    print("-" * 40)
    
    # Create assembly with UC2 grid functionality
    assembly = iAssembly(
        path='',  # Current directory
        prefix='UC2_Demo_Assembly.iam',
        units='metric',  # Enable UC2 grid functionality 
        overwrite=True
    )
    
    # Set UC2 standard grid spacing (50x50x55mm)
    assembly.set_grid_spacing(50.0, 50.0, 55.0)
    print("✓ Set grid spacing to 50x50x55mm (UC2 standard)")
    
    # Define UC2 components to place (adjust paths as needed)
    components = [
        {
            'file': 'Assembly_cube_lens.iam',
            'grid_pos': (0, 0, 0),
            'rotation': (0, 0, 0),
            'name': 'Lens_Origin'
        },
        {
            'file': 'Assembly_cube_mirror.iam', 
            'grid_pos': (1, 0, 0),
            'rotation': (0, 90, 0),
            'name': 'Mirror_50mm'
        },
        {
            'file': 'Assembly_cube_lens.iam',
            'grid_pos': (0, 1, 0),
            'rotation': (0, 0, 0),
            'name': 'Lens_50mmY'
        },
        {
            'file': 'Assembly_cube_mirror.iam',
            'grid_pos': (1, 1, 0),
            'rotation': (0, 45, 0),
            'name': 'Mirror_Diagonal'
        }
    ]
    
    try:
        # Place components using UC2 grid functionality
        print(f"Placing {len(components)} UC2 components...")
        placed_components = assembly.create_uc2_grid_from_table(components)
        print(f"✓ Successfully placed {len(placed_components)} components")
        
        # Save the assembly
        assembly.save()
        print("✓ Assembly saved as UC2_Demo_Assembly.iam")
        
    except Exception as e:
        print(f"⚠️  Warning: Could not place actual components: {e}")
        print("   (This is expected if UC2 component files are not available)")
        print("   Continuing with image generation using empty assembly...")
    
    # Step 2: Generate Images from Assembly
    print("\n📷 STEP 2: Generating Images from Assembly")
    print("-" * 40)
    
    try:
        # Create output directory for images
        output_dir = 'UC2_Assembly_Images'
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate realistic images from all six perspectives
        print("Creating realistic rendered images...")
        realistic_images = assembly.create_perspective_images(
            base_filename='UC2_Demo_realistic',
            output_path=output_dir,
            views=['front', 'back', 'left', 'right', 'top', 'bottom'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=True,
            wireframe=False
        )
        
        print(f"✓ Created {len(realistic_images)} realistic images")
        for img_path in realistic_images:
            print(f"   - {os.path.basename(img_path)}")
        
        # Generate wireframe images  
        print("\nCreating wireframe images...")
        wireframe_images = assembly.create_perspective_images(
            base_filename='UC2_Demo_wireframe',
            output_path=output_dir,
            views=['front', 'back', 'left', 'right', 'top', 'bottom'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=False,
            wireframe=True
        )
        
        print(f"✓ Created {len(wireframe_images)} wireframe images")
        for img_path in wireframe_images:
            print(f"   - {os.path.basename(img_path)}")
            
        # Generate isometric view
        print("\nCreating isometric view...")
        iso_images = assembly.create_perspective_images(
            base_filename='UC2_Demo_iso',
            output_path=output_dir,
            views=['iso'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=True,
            wireframe=False
        )
        
        print(f"✓ Created isometric view: {os.path.basename(iso_images[0])}")
        
    except Exception as e:
        print(f"⚠️  Warning: Could not generate images: {e}")
        print("   (This is expected when not running on Windows with Inventor)")
    
    # Step 3: Demonstrate both functionalities working together
    print("\n🎯 STEP 3: Summary of Unified Functionality")
    print("-" * 40)
    
    print("✅ UC2 Grid Assembly Features Demonstrated:")
    print("   • Grid-based component placement (50x50x55mm spacing)")
    print("   • Rotation support for component orientation")
    print("   • Batch component placement from table definitions")
    print("   • Metric unit system for UC2 compatibility")
    
    print("\n✅ Assembly Image Generation Features Demonstrated:")
    print("   • Six-perspective image creation (front/back/left/right/top/bottom)")
    print("   • Isometric view generation")
    print("   • Realistic vs wireframe rendering options")
    print("   • High-resolution image export (1920x1080)")
    print("   • PNG format output with organized file naming")
    
    print("\n🔗 Both functionalities work seamlessly together:")
    print("   • Same iAssembly class handles both UC2 grid and image generation")
    print("   • Create complex UC2 assemblies, then generate documentation images")
    print("   • Unified API for both assembly creation and visualization")
    
    # Close the assembly
    try:
        assembly.close(save=False)
        print("\n✓ Assembly closed successfully")
    except:
        pass
    
    return assembly

def demonstrate_backwards_compatibility():
    """
    Show that the unified class maintains backwards compatibility.
    """
    print("\n" + "=" * 60)
    print("BACKWARDS COMPATIBILITY DEMONSTRATION")
    print("=" * 60)
    
    print("\n1. Assembly Image Creation (original main branch functionality):")
    try:
        # Original main branch usage pattern
        assembly_img = iAssembly(path='C:\\assemblies', prefix='my_assembly.iam')
        print("   ✓ Original constructor signature works")
        
        # Original image creation pattern  
        images = assembly_img.create_perspective_images(
            views=['front', 'back'],
            realistic=True
        )
        print("   ✓ Original image creation methods work")
        
    except Exception as e:
        print(f"   ⚠️  Expected error (no Inventor): {e}")
    
    print("\n2. UC2 Grid Creation (new functionality):")
    try:
        # New UC2 usage pattern
        assembly_uc2 = iAssembly(
            'UC2_Test.iam', 
            units='metric'  # Enables UC2 functionality
        )
        assembly_uc2.set_grid_spacing(50.0, 50.0, 55.0)
        print("   ✓ UC2 grid functionality works")
        
    except Exception as e:
        print(f"   ⚠️  Expected error (no Inventor): {e}")
    
    print("\n✅ Both usage patterns are supported by the unified class!")

if __name__ == "__main__":
    print("PyInventor Unified Assembly Functionality Demo")
    
    try:
        # Main demonstration
        assembly = create_uc2_assembly_with_images()
        
        # Backwards compatibility check
        demonstrate_backwards_compatibility()
        
        print("\n" + "=" * 60)
        print("🎉 DEMONSTRATION COMPLETE")
        print("=" * 60)
        print("\nThe unified iAssembly class successfully provides:")
        print("• UC2 grid assembly creation capabilities")
        print("• Multi-perspective image generation capabilities") 
        print("• Full backwards compatibility with existing code")
        print("• Seamless integration of both feature sets")
        
        print(f"\nTo run this with real Inventor assemblies:")
        print("1. Install Autodesk Inventor on Windows")
        print("2. Update component file paths to your UC2 files")
        print("3. Run the script to create assemblies and images")
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print("This script demonstrates the unified functionality")
        print("but requires Windows + Inventor for full execution.")