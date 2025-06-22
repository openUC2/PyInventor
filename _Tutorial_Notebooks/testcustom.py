import PyInventor
from PyInventor import *
import time
import numpy as np


part = iPart(path='C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\MAS',
             prefix='MAS - 2020 - Lens Inserts - V04.ipt',
             units='imperial',
             overwrite=False)

# Debug: Check if methods exist
print("Available methods in iPart:")
methods = [method for method in dir(part) if not method.startswith('_')]
print(f"Total methods: {len(methods)}")
if 'list_bodies' in methods:
    print("✓ list_bodies method found")
else:
    print("✗ list_bodies method NOT found")
    
if 'debug_info' in methods:
    print("✓ debug_info method found")
    debug = part.debug_info()
    print(f"Debug info: {debug}")
else:
    print("✗ debug_info method NOT found")

# Set parameter value
part.set_parameter('LensDiam', 15)

# List all available bodies in the part
print("Available bodies:")
try:
    body_names = part.list_bodies()
    for name in body_names:
        print(f"  - {name}")
except AttributeError as e:
    print(f"AttributeError: {e}")
    print("This suggests the methods are not properly loaded. Try restarting Python and Inventor.")
except Exception as e:
    print(f"Other error: {e}")

# Show or isolate specific body (example with first body if available)
if 'body_names' in locals() and body_names:
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
if 'body_names' in locals() and body_names:
    for body_name in body_names:
        part.export_body_as(body_name)
