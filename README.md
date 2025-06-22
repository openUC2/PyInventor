# PyInventor
 A Python based Autodesk Inventor API module!

Welcome to PyInventor! The following is a module that allows for the creation of parts using Autodesk Inventor. I wrote this with the intent of automating the frustratingly slow process of 
parametrically varying features in inventor either by hand or using the tedius parameter editor or the built in VBA editor (iLogic). The pyinvent library is a wrapper for the Autodesk 
Inventor API library which is natively written in VBA (Visual Basic for Applications). Because of this both Autodesk Inventor and this library only work in Microsoft Windows. MacOS is 
completely incompatible (unless running Windows in bootcamp). 

This package does not require the Schuster Lab Library (slab) to run and can be used with any normal Anaconda 3.2 install or higher with no additional packages. Of course Autodesk Inventor is required. 
It is recommended that Inventor 2019 is used for best compatibility however this will run using Inventor 2017 or later (in theory), however the older variants have not been tested in depth. Anything 
after Inventor 2019 will also be compatible. For more information on this compatibility and to learn more about the Inventor API and its functionality please refer to the API manual:

http://help.autodesk.com/view/INVNTOR/2019/ENU/

This is version 0.4 of PyInventor and only allows for individual part creation and export. Not all 3D functionality has been added. The demos (located in the _Totorial_Notebooks folder) demonstrate the current extents of 
PyInventor's capabilities. New revisions will likely be added in time.

## NEW FEATURES (v0.4.1):

### Body Management and Export
PyInventor now supports working with multiple bodies in existing IPT files:

- **`list_bodies()`** - Get list of all bodies in a part
- **`get_body(name)`** - Retrieve a specific body by name  
- **`show_only_body(body)`** - Hide all bodies except the specified one
- **`show_all_bodies()`** - Make all bodies visible
- **`export_body_as(body, filename)`** - Export individual bodies as STP files
- **`set_parameter(name, value)`** - Modify parameters in existing parts

Example usage:
```python
# Open existing IPT file
part = iPart(path='C:\\path\\to\\file', prefix='part.ipt', overwrite=False)

# Modify parameters
part.set_parameter('LensDiam', 15)

# Work with bodies
bodies = part.list_bodies()
for body_name in bodies:
    part.export_body_as(body_name)  # Export each body as STP
```

See `_Tutorial_Notebooks/body_export_example.py` for a complete example.

RECOMMENDED INSTALL PROCESS:
________________________________________________________________
Open a cmd window and run: python setup.py install

Then import pyinvent directly


~Andrew Oriani
oriani@uchicago.edu
