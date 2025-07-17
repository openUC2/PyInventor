# Assembly Image Creation Feature

This document describes the new assembly image creation functionality added to PyInventor.

## Overview

The new feature allows you to automatically create images of Autodesk Inventor assembly files (IAM) from six different perspectives with various rendering options. This addresses the requirement to batch process assemblies and generate documentation images.

## New Classes and Functions

### `iAssembly` Class

A new class for handling Inventor assembly documents, similar to the existing `iPart` class but specifically for assemblies.

#### Key Methods:

- **`__init__(path, prefix, overwrite=False)`** - Initialize and open an assembly
- **`set_view_orientation(view_type)`** - Set camera to standard views ('front', 'back', 'left', 'right', 'top', 'bottom', 'iso')
- **`set_visual_style(shaded, edges, hidden_edges, realistic)`** - Control rendering appearance
- **`export_image(filename, file_path, image_format, width, height)`** - Export current view as image
- **`create_perspective_images(...)`** - Create images from multiple perspectives automatically
- **`close(save=False)`** - Close the assembly document

### `create_assembly_images_batch()` Function

A utility function for batch processing multiple assembly files in a folder.

## Usage Examples

### Single Assembly Processing

```python
from PyInventor import iAssembly

# Open an assembly
assembly = iAssembly(path='C:\\assemblies', prefix='my_assembly.iam')

# Create images from all six perspectives with realistic rendering
images = assembly.create_perspective_images(
    base_filename='my_assembly_realistic',
    views=['front', 'back', 'left', 'right', 'top', 'bottom'],
    realistic=True,
    wireframe=False
)

# Create wireframe images for technical documentation
wireframe_images = assembly.create_perspective_images(
    base_filename='my_assembly_wireframe', 
    views=['front', 'top', 'right'],
    realistic=False,
    wireframe=True
)

assembly.close()
```

### Batch Processing Multiple Assemblies

```python
from PyInventor import create_assembly_images_batch

# Process all IAM files in a folder
results = create_assembly_images_batch(
    assembly_folder='C:\\my_assemblies',
    output_folder='C:\\output_images',
    views=['front', 'back', 'left', 'right', 'top', 'bottom'],
    realistic=True,
    wireframe=False
)

# Process with wireframe rendering
wireframe_results = create_assembly_images_batch(
    assembly_folder='C:\\my_assemblies',
    output_folder='C:\\wireframe_images', 
    views=['front', 'top', 'iso'],
    realistic=False,
    wireframe=True
)
```

## Supported Features

### View Perspectives
- **Front** - Front view of the assembly
- **Back** - Back view of the assembly  
- **Left** - Left side view
- **Right** - Right side view
- **Top** - Top view (plan view)
- **Bottom** - Bottom view
- **Iso** - Isometric view (3D perspective)

### Rendering Options
- **Realistic** - Photorealistic rendering with materials and lighting
- **Wireframe** - Line-based technical drawing style
- **Shaded** - Standard shaded view with or without edges
- **Hidden edges** - Control visibility of hidden edges

### Image Formats
- PNG (default, best quality)
- JPG/JPEG (smaller file size)
- BMP (uncompressed)
- TIF/TIFF (high quality)

### Image Resolutions
- Custom width and height in pixels
- Common presets:
  - HD: 1920x1080
  - 4K: 3840x2160  
  - Preview: 800x600
  - Technical: 2048x1536

## Requirements

- Windows operating system
- Autodesk Inventor installed (2017 or later, 2019+ recommended)
- PyInventor dependencies (win32com, etc.)
- Assembly files (.iam) to process

## Error Handling

The functions include comprehensive error handling:
- Invalid file paths or missing assemblies
- Unsupported view orientations
- Image export failures
- COM interface errors

Errors are reported with descriptive messages, and batch processing continues even if individual assemblies fail.

## File Organization

Images are automatically organized into folders:
- Single assembly: Creates subfolders by rendering type
- Batch processing: Creates subfolders for each assembly
- Naming convention: `{assembly_name}_{view_type}.{format}`

## Integration with Existing Code

The new functionality is fully integrated with the existing PyInventor codebase:
- Uses the same COM initialization (`com_obj` base class)
- Compatible visual style settings
- Consistent file handling patterns
- Same error handling approach

This maintains backward compatibility while adding powerful new capabilities for assembly documentation and visualization.