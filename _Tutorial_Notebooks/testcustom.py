import PyInventor
from PyInventor import *
import time
import numpy as np



part = iPart(path='C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\MAS',
             prefix='MAS - 2020 - Lens Inserts - V04.ipt',
             units='imperial',
             overwrite=False)

# Set parameter value
part.set_parameter('LensDiam', 15)

# List all available bodies in the part
print("Available bodies:")
body_names = part.list_bodies()
for name in body_names:
    print(f"  - {name}")

# Show or isolate specific body (example with first body if available)
if body_names:
    first_body_name = body_names[0]
    body_target = part.get_body(first_body_name)
    part.show_only_body(body_target)
    
    # Export the isolated body as STP
    part.export_body_as(body_target, copy_name=f'{first_body_name}_modified.stp')
    
    # Show all bodies again
    part.show_all_bodies()

# Save the modified part
part.save()

# Export all bodies individually as STP files
for body_name in body_names:
    part.export_body_as(body_name)
