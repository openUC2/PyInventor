"""
Example: Creating Images from Assembly Files

This example demonstrates how to:
1. Open assembly files (IAM) 
2. Create images from six different perspectives (front, back, left, right, top, bottom)
3. Choose rendering options (realistic vs wireframe)
4. Batch process multiple assemblies in a folder

This addresses the GitHub issue requirement for creating images for assemblies
from different perspectives with various rendering options.
"""

import PyInventor
from PyInventor import *
import os


def single_assembly_example():
    """Example of creating images for a single assembly file."""
    
    print("=== Single Assembly Image Creation Example ===")
    
    # Check if we have a real assembly file to work with
    # Look for any .iam files in the current directory first
    current_dir = os.getcwd()
    iam_files = [f for f in os.listdir(current_dir) if f.endswith('.iam')]
    
    if iam_files:
        assembly_path = current_dir
        assembly_file = iam_files[0]
        print(f"Found assembly file: {assembly_file}")
    else:
        # Use the example paths but create a new assembly if file doesn't exist
        assembly_path = r'C:\path\to\your\assembly\folder'
        assembly_file = 'sample_assembly.iam'
        print(f"Using example paths - will create new assembly if file doesn't exist")
    
    try:
        # Open the assembly (or create new one if file doesn't exist)
        assembly = iAssembly(path=assembly_path, prefix=assembly_file, overwrite=False)
        print(f"Opened assembly: {assembly_file}")
        
        # Create images with realistic rendering
        print("\n1. Creating realistic rendered images...")
        realistic_images = assembly.create_perspective_images(
            base_filename='sample_realistic',
            output_path=os.path.join(assembly_path, 'realistic_images'),
            views=['front', 'back', 'left', 'right', 'top', 'bottom'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=True,
            wireframe=False
        )
        
        # Create images with wireframe rendering  
        print("\n2. Creating wireframe images...")
        wireframe_images = assembly.create_perspective_images(
            base_filename='sample_wireframe',
            output_path=os.path.join(assembly_path, 'wireframe_images'),
            views=['front', 'back', 'left', 'right', 'top', 'bottom'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=False,
            wireframe=True
        )
        
        # Create isometric view
        print("\n3. Creating isometric view...")
        iso_images = assembly.create_perspective_images(
            base_filename='sample_iso',
            output_path=os.path.join(assembly_path, 'iso_images'),
            views=['iso'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=True,
            wireframe=False
        )
        
        # Close the assembly
        assembly.close(save=False)
        
        print(f"\n=== Summary ===")
        print(f"- Created {len(realistic_images)} realistic images")
        print(f"- Created {len(wireframe_images)} wireframe images") 
        print(f"- Created {len(iso_images)} isometric images")
        
        print(f"\nRealistic images:")
        for img in realistic_images:
            print(f"  - {img}")
            
        print(f"\nWireframe images:")
        for img in wireframe_images:
            print(f"  - {img}")
            
        print(f"\nIsometric images:")
        for img in iso_images:
            print(f"  - {img}")
            
    except Exception as e:
        print(f"Error: {str(e)}")


def batch_processing_example():
    """Example of batch processing multiple assemblies in a folder."""
    
    print("\n=== Batch Assembly Processing Example ===")
    
    # Folder containing multiple assembly files
    assembly_folder =  'C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\ASS\\'
    assembly_folder =  'C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\KIT\\'
    output_folder =   os.path.join(assembly_folder, 'output')
    
    try:
        # Process all assemblies with realistic rendering
        print("1. Processing all assemblies with realistic rendering...")
        realistic_results = create_assembly_images_batch(
            assembly_folder=assembly_folder,
            output_folder=os.path.join(output_folder, 'realistic'),
            views=['iso'], #'front', 'back', 'left', 'right', 'top', 'bottom'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=True,
            wireframe=False
        )
        
        # Process all assemblies with wireframe rendering
        print("\n2. Processing all assemblies with wireframe rendering...")
        wireframe_results = create_assembly_images_batch(
            assembly_folder=assembly_folder,
            output_folder=os.path.join(output_folder, 'wireframe'),
            views=['front', 'back', 'left', 'right', 'top', 'bottom'],
            image_format='png',
            width=1920,
            height=1080,
            realistic=False,
            wireframe=True
        )
        
        # Process assemblies for just key views (front, top, iso)
        print("\n3. Processing assemblies for key views only...")
        key_view_results = create_assembly_images_batch(
            assembly_folder=assembly_folder,
            output_folder=os.path.join(output_folder, 'key_views'),
            views=['front', 'top', 'iso'],
            image_format='jpg',
            width=1280,
            height=720,
            realistic=True,
            wireframe=False
        )
        
        print(f"\n=== Batch Processing Summary ===")
        print(f"- Processed {len(realistic_results)} assemblies for realistic rendering")
        print(f"- Processed {len(wireframe_results)} assemblies for wireframe rendering")
        print(f"- Processed {len(key_view_results)} assemblies for key views")
        
        print(f"\nDetailed results:")
        for assembly_name, image_paths in realistic_results.items():
            print(f"  {assembly_name}: {len(image_paths)} realistic images")
        
        for assembly_name, image_paths in wireframe_results.items():
            print(f"  {assembly_name}: {len(image_paths)} wireframe images")
            
        for assembly_name, image_paths in key_view_results.items():
            print(f"  {assembly_name}: {len(image_paths)} key view images")
        
    except Exception as e:
        print(f"Error: {str(e)}")


def custom_rendering_example():
    """Example of creating images with custom rendering settings."""
    
    print("\n=== Custom Rendering Example ===")
    
    assembly_path =  'C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\ASS\\'
    assembly_file = 'ASS - 2016 - CUBMIR45°90° - V04.iam'
    
    try:
        # Open the assembly
        assembly = iAssembly(path=assembly_path, prefix=assembly_file, overwrite=False)
        
        # Create high-resolution images for documentation
        print("Creating high-resolution documentation images...")
        doc_images = assembly.create_perspective_images(
            base_filename='documentation',
            output_path=os.path.join(assembly_path, 'documentation'),
            views=['front', 'iso'],
            image_format='png',
            width=3840,  # 4K resolution
            height=2160,
            realistic=True,
            wireframe=False
        )
        
        # Create quick preview images
        print("Creating quick preview images...")
        preview_images = assembly.create_perspective_images(
            base_filename='preview',
            output_path=os.path.join(assembly_path, 'previews'),
            views=['front', 'back', 'left', 'right', 'top', 'bottom'],
            image_format='jpg',
            width=800,
            height=600,
            realistic=False,
            wireframe=False
        )
        
        # Create technical drawings (wireframe)
        print("Creating technical drawing images...")
        technical_images = assembly.create_perspective_images(
            base_filename='technical',
            output_path=os.path.join(assembly_path, 'technical'),
            views=['front', 'top', 'right'],
            image_format='png',
            width=2048,
            height=1536,
            realistic=False,
            wireframe=True
        )
        
        assembly.close(save=False)
        
        print(f"\n=== Custom Rendering Summary ===")
        print(f"- Created {len(doc_images)} high-resolution documentation images")
        print(f"- Created {len(preview_images)} quick preview images")
        print(f"- Created {len(technical_images)} technical drawing images")
        
    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    print("PyInventor Assembly Image Creation Examples")
    print("=" * 50)
    
    try:
        # Run examples (comment out the ones you don't need)
        
        # Single assembly example
        #single_assembly_example()
        
        # Batch processing example
        batch_processing_example()
        
        # Custom rendering example
        # custom_rendering_example()
        
    except Exception as e:
        print(f"Example execution error: {str(e)}")
        print("\nNote: These examples require:")
        print("1. Windows operating system")
        print("2. Autodesk Inventor installed") 
        print("3. Assembly files (*.iam) to process")
        print("4. PyInventor dependencies (win32com, etc.)")
        print("5. Update the file paths in the examples to match your setup")