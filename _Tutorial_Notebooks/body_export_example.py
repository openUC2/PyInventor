"""
Example: Working with Bodies in Existing IPT Files

This example demonstrates how to:
1. Open an existing IPT file (not create a new one)
2. Modify parameters in the parameter table
3. List and manage individual bodies
4. Export specific bodies as STP files

This addresses the requirements from the GitHub issue about modifying
parameters and exporting multiple bodies separately.
"""

import PyInventor
from PyInventor import *
import os

def main():
    # Open existing IPT file (set overwrite=False to open existing file)
    part = iPart(path='C:\\Users\\benir\\Documents\\openUC2-CAD-new\\workspace\\MAS',
                 prefix='MAS - 2020 - Lens Inserts - V04.ipt',
                 units='imperial',
                 overwrite=False)
    
    print("=== PyInventor Body Export Example ===")
    
    # 1. Modify parameter in the part
    print("\n1. Setting parameter 'LensDiam' to 15...")
    part.set_parameter('LensDiam', 15)
    print("Parameter updated successfully.")
    
    # 2. List all available bodies in the part
    print("\n2. Listing all bodies in the part:")
    body_names = part.list_bodies()
    if not body_names:
        print("  No bodies found in the part.")
        return
    
    for i, name in enumerate(body_names, 1):
        print(f"  {i}. {name}")
    
    # 3. Work with individual bodies
    print(f"\n3. Working with bodies (found {len(body_names)} bodies):")
    
    # Example: Isolate and export the first body
    if len(body_names) > 0:
        first_body_name = body_names[0]
        print(f"\n   a) Isolating body: '{first_body_name}'")
        body_target = part.get_body(first_body_name)
        part.show_only_body(body_target)
        
        # Export the isolated body
        print(f"   b) Exporting '{first_body_name}' as STP...")
        export_path = part.export_body_as(body_target, 
                                         copy_name=f'{first_body_name}_LensDiam15.stp')
        print(f"      Exported to: {export_path}")
        
        # Restore visibility of all bodies
        print("   c) Restoring visibility of all bodies...")
        part.show_all_bodies()
    
    # 4. Export all bodies individually (batch export)
    print(f"\n4. Batch exporting all {len(body_names)} bodies as STP files:")
    export_paths = []
    for body_name in body_names:
        try:
            export_path = part.export_body_as(body_name)
            export_paths.append(export_path)
            print(f"   ✓ Exported: {body_name}")
        except Exception as e:
            print(f"   ✗ Failed to export {body_name}: {str(e)}")
    
    # 5. Save the modified part
    print("\n5. Saving the modified part...")
    part.save()
    print("Part saved successfully.")
    
    print(f"\n=== Summary ===")
    print(f"- Modified parameter 'LensDiam' to 15")
    print(f"- Found {len(body_names)} bodies in the part")
    print(f"- Successfully exported {len(export_paths)} STP files")
    print(f"- Saved modified part file")
    
    if export_paths:
        print(f"\nExported files:")
        for path in export_paths:
            print(f"  - {path}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nNote: This example requires:")
        print("1. Windows operating system")
        print("2. Autodesk Inventor installed")
        print("3. The specified IPT file to exist")
        print("4. PyInventor dependencies (win32com, etc.)")