# UC2 Grid Assembly Documentation

## Overview

PyInventor now supports creating complex UC2 assemblies in grid patterns using the unified `iAssembly` class. This functionality allows you to place UC2 cubes (or any Inventor components) in a 50x50x55mm grid with specific positions and orientations.

**NEW**: The `iAssembly` class now combines UC2 grid assembly creation with assembly image generation capabilities, providing a complete solution for both creating and documenting UC2 assemblies.

## Combined Features

### UC2 Grid Assembly Features
- **Grid-based component placement**: Place components at grid coordinates that automatically convert to real-world positions
- **Flexible rotations**: Apply rotations around X, Y, and Z axes
- **CSV import**: Define assemblies using CSV files for easy editing
- **Multiple grid patterns**: Create rectangular grids, alternating patterns, and custom layouts
- **Batch operations**: Place multiple components with a single function call

### Assembly Image Generation Features  
- **Six-perspective views**: Generate front, back, left, right, top, bottom views
- **Multiple rendering options**: Realistic, wireframe, shaded with edge control
- **Batch processing**: Process multiple assemblies automatically
- **High-resolution export**: PNG, JPG, BMP, TIF formats with custom resolutions
- **Organized output**: Automatic folder organization and consistent naming

## Getting Started

### Basic UC2 Grid Assembly

```python
from PyInventor import iAssembly

# Create a new assembly with UC2 grid functionality
assembly = iAssembly(
    path='C:\\UC2_Assemblies',
    prefix='MyUC2Assembly.iam',
    units='metric',  # Enable UC2 grid functionality with metric units
    overwrite=True
)

# Set standard UC2 grid spacing (50x50x55mm)
assembly.set_grid_spacing(50.0, 50.0, 55.0)

# Place a lens cube at the origin
assembly.place_component_at_grid(
    component_path='C:\\UC2\\Assembly_cube_lens.iam',
    grid_x=0, grid_y=0, grid_z=0,
    rotation=(0, 0, 0)
)

# Place a mirror cube at (50,0,0)mm with 90° rotation
assembly.place_component_at_grid(
    component_path='C:\\UC2\\Assembly_cube_mirror.iam', 
    grid_x=1, grid_y=0, grid_z=0,
    rotation=(0, 90, 0)
)

# Save the assembly
assembly.save()
```

### Generate Images from Created Assembly

```python
# After creating the UC2 assembly, generate documentation images
images = assembly.create_perspective_images(
    base_filename='MyUC2Assembly',
    output_path='C:\\UC2_Images',
    views=['front', 'back', 'left', 'right', 'top', 'bottom'],
    image_format='png',
    width=1920,
    height=1080,
    realistic=True
)

print(f"Created {len(images)} documentation images")
```

### Complete Workflow Example

```python
from PyInventor import iAssembly

# 1. Create UC2 assembly
assembly = iAssembly('UC2_Complete_Demo.iam', units='metric', overwrite=True)
assembly.set_grid_spacing(50.0, 50.0, 55.0)

# 2. Define UC2 components
components = [
    {'file': 'Assembly_cube_lens.iam', 'grid_pos': (0, 0, 0), 'rotation': (0, 0, 0)},
    {'file': 'Assembly_cube_mirror.iam', 'grid_pos': (1, 0, 0), 'rotation': (0, 90, 0)},
    {'file': 'Assembly_cube_lens.iam', 'grid_pos': (0, 1, 0), 'rotation': (0, 0, 0)},
]

# 3. Create the assembly
placed_components = assembly.create_uc2_grid_from_table(components)
assembly.save()

# 4. Generate documentation images
realistic_images = assembly.create_perspective_images(
    base_filename='UC2_Demo_realistic',
    views=['front', 'back', 'left', 'right', 'top', 'bottom'],
    realistic=True
)

wireframe_images = assembly.create_perspective_images(
    base_filename='UC2_Demo_wireframe', 
    views=['front', 'back', 'left', 'right', 'top', 'bottom'],
    wireframe=True
)

# 5. Close assembly
assembly.close()

print("✅ UC2 assembly created and documented!")
```

### Using Component Tables

For complex assemblies, use component tables:

```python
uc2_components = [
    {
        'name': 'Lens_Origin',
        'file': 'C:\\UC2\\Assembly_cube_lens.iam',
        'grid_pos': (0, 0, 0),
        'rotation': (0, 0, 0)
    },
    {
        'name': 'Mirror_50mm',
        'file': 'C:\\UC2\\Assembly_cube_mirror.iam',
        'grid_pos': (1, 0, 0), 
        'rotation': (0, 90, 0)
    }
]

placed_components = assembly.create_uc2_grid_from_table(uc2_components)
```

### CSV Workflow

1. **Generate a sample CSV**:
```python
from uc2_grid_utilities import generate_sample_csv
generate_sample_csv('my_components.csv')
```

2. **Edit the CSV file** with your component paths and positions

3. **Create assembly from CSV**:
```python
from uc2_grid_utilities import create_uc2_assembly_from_csv
assembly = create_uc2_assembly_from_csv('my_components.csv')
```

## API Reference

### iAssembly Class

#### Constructor
```python
iAssembly(path='', prefix='', units='imperial', overwrite=True)
```

- `path`: Directory for the assembly file
- `prefix`: Assembly filename (.iam extension)
- `units`: 'imperial' or 'metric'
- `overwrite`: Whether to overwrite existing files

#### Key Methods

**set_grid_spacing(x_spacing, y_spacing, z_spacing)**
Set the grid spacing in current units.

**place_component(component_path, position, rotation)**
Place a component at absolute position.

**place_component_at_grid(component_path, grid_x, grid_y, grid_z, rotation)**
Place a component at grid coordinates.

**create_uc2_grid_from_table(component_table)**
Place multiple components from a table definition.

### Utility Functions

**create_uc2_assembly_from_csv(csv_file_path, assembly_name, assembly_path, grid_spacing)**
Create assembly from CSV file.

**create_rectangular_grid(width, height, layers, component_file, assembly_name, assembly_path)**
Create a uniform rectangular grid.

**create_alternating_pattern(width, height, component_files, assembly_name, assembly_path)**
Create alternating/checkerboard patterns.

## File Formats

### CSV Format
```csv
name,file_path,grid_x,grid_y,grid_z,rot_x,rot_y,rot_z
Lens_Origin,C:/UC2/Assembly_cube_lens.iam,0,0,0,0,0,0
Mirror_50mm,C:/UC2/Assembly_cube_mirror.iam,1,0,0,0,90,0
```

### Component Table Format
```python
component = {
    'name': 'Component_Name',           # Display name
    'file': 'path/to/component.iam',    # Full file path
    'grid_pos': (x, y, z),              # Grid coordinates (integers)
    'rotation': (rx, ry, rz)            # Rotation angles in degrees (optional)
}
```

## Grid Coordinate System

- **Grid coordinates** are integers (0, 1, 2, ...)
- **Actual positions** = grid_coords × grid_spacing
- **Default spacing**: 50mm (X), 50mm (Y), 55mm (Z)

Examples:
- Grid (0,0,0) → Position (0,0,0)mm
- Grid (1,0,0) → Position (50,0,0)mm  
- Grid (2,3,1) → Position (100,150,55)mm

## Rotation System

Rotations are applied in Z-Y-X order:
1. Rotation around Z-axis (yaw)
2. Rotation around Y-axis (pitch)  
3. Rotation around X-axis (roll)

Angles are in degrees (converted to radians internally).

## Examples

### Example 1: Basic UC2 Setup
```python
# Recreate the issue example exactly
assembly = iAssembly(prefix='UC2_Basic.iam', units='metric')
assembly.set_grid_spacing(50.0, 50.0, 55.0)

# Assembly_cube_lens.iam at 0,0,0 at orientation 0,0
assembly.place_component_at_grid(
    'Assembly_cube_lens.iam', 0, 0, 0, (0, 0, 0)
)

# Assembly_cube_mirror.iam at 50,0,0 at angle 0,90  
assembly.place_component_at_grid(
    'Assembly_cube_mirror.iam', 1, 0, 0, (0, 90, 0)
)

assembly.save()
```

### Example 2: Large Grid
```python
from uc2_grid_utilities import create_rectangular_grid

# Create 5x5x2 grid of lens components
assembly = create_rectangular_grid(
    width=5, height=5, layers=2,
    component_file='Assembly_cube_lens.iam',
    assembly_name='Large_UC2_Grid.iam'
)
```

### Example 3: Mixed Components
```python
from uc2_grid_utilities import create_alternating_pattern

# Alternating lens and mirror cubes
assembly = create_alternating_pattern(
    width=4, height=4,
    component_files=[
        'Assembly_cube_lens.iam',
        'Assembly_cube_mirror.iam'
    ],
    assembly_name='Checkerboard_UC2.iam'
)
```

## Requirements

- Windows operating system
- Autodesk Inventor (2017 or later, 2019+ recommended)
- Python 3.6+
- PyInventor dependencies (win32com, numpy, etc.)

## Troubleshooting

**File not found errors**: Ensure component file paths are correct and files exist.

**COM errors**: Make sure Inventor is installed and can be launched.

**Unit conversion issues**: Use 'metric' units for mm measurements, 'imperial' for inches.

**Rotation problems**: Remember rotations are in degrees and applied in Z-Y-X order.

## Files Included

- `uc2_grid_example.py` - Complete example script
- `uc2_grid_utilities.py` - Utility functions  
- `sample_uc2_components.csv` - Example CSV file
- `test_uc2_grid.py` - Test script