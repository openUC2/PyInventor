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

This is version 0.4.1 of PyInventor and now supports both individual part creation and assembly image generation! The part creation functionality allows for individual part creation and export. The new assembly functionality allows creating images from multiple perspectives with various rendering options. Not all 3D functionality has been added for parts. The demos (located in the _Tutorial_Notebooks folder) demonstrate the current extents of 
PyInventor's capabilities. New revisions will likely be added in time.

## Part probe: Inventor -> JSON geometry recipes

`inventor_part_probe.py` connects to a running Inventor instance and dumps a
part's complete geometry recipe as JSON: parameters (model/user/reference,
converted to mm/deg), the ordered feature tree with per-feature parameters,
extrude/revolve profile paths (exact sketch curves), sketches with dimension
expressions, work features, and the final b-rep inventory (face geometry,
vertices, mass properties). Optionally exports a STEP copy. Documents that
are already open in the session are probed in place without disturbing it.

```bash
python inventor_part_probe.py "PRT - 2027 - INSLEND43F-50 - V04.ipt" --out-dir extracted --step
```

This is how the openUC2 V4 inserts were reverse-parametrized into CadQuery
(see `openuc2-cadquery/uc2v4` and `openuc2-cadquery/extracted/README.md`).
Derived parts carry no recipe of their own — probe the MAS master models for
the sketch/feature data, the derived part for the released b-rep.

## Shape export: an assembly STEP without the screws

`export_shape_step.py` exports an assembly to STEP with only the parts that
give it its shape. Electronics (the FRAME's `5xxx` numbering, `BRD -`,
`ELE -`, boards, the Pi), fasteners, cables, the puzzle joints, the `PRT-2xxx`
cube inserts and purchased parts that are not a camera, objective, lens,
mirror or motor are hidden before Inventor writes the file. FRAME #0008:
269.5 MB → 27.7 MB, same node names and poses, export in 17 s.

```bash
python export_shape_step.py "FRAME #0008 - Microscope incl accessories.iam" --out C:\exports
python export_shape_step.py "…iam" --dry-run                    # what would go, and why
python export_shape_step.py "…iam" --keep "Electronics box" "HIKROBOT" --skip-rule insert
python export_shape_step.py --dump-rules > rules.json            # edit, then --config rules.json
```

It is safe to run on a file you have open, even with unsaved edits: the work
happens on a private sibling copy of the top-level `.iam` (same folder, so
every reference resolves) that is closed without saving and deleted, and
nothing is suppressed — Inventor's STEP writer skips hidden components, and
`Visible = False` can be set on any sub-occurrence from the parent, which
`Suppress` cannot. The assembly's project must be the active one (a file
outside it opens read-only). A `.report.json` beside the STEP lists every
hidden occurrence and the rule that hid it.

`export_named_step.py` exports a manifest of parts/assemblies to STEP with an
iProperties and range-box probe per file; `assembly_tree.py` prints an
assembly's occurrence tree with positions.

## Assembly manuals: exploded view, parts list and IKEA-style steps as PDF

`assembly_manual.py` turns a module assembly into assembly instructions on the
openUC2 A3 sheet (template `Standard_openUC2_2025.idw`, title block filled from
the module's iProperties), without a hand-made presentation file:

* page 1: the whole module exploded, balloons and the BAUTEILLISTE, like the
  existing `.ipn`/`.idw` drawings;
* one page per step: big step number, a table of the parts that go in (parts-list
  item, quantity, part number), and a picture of what is already assembled with
  the new parts hovering along the direction they go in, arrows beside the big
  ones and dashed lines into the hole for screws. `SUB - …` pre-assemblies are
  built first ("3x" when a module holds several identical ones) and later appear
  as "aus Schritt 1-5".

```bash
python assembly_manual.py "…\ASS - 2067 - CUBLENASP20- V04.iam" --out MANUALS
python assembly_manual.py "…\workspace\ASS" --pattern "ASS - 20*.iam" --out MANUALS   # a folder
python assembly_manual.py --kit "…\workspace\KIT" --out MANUALS        # every module of every kit (newest batch)
python assembly_manual.py --kit "…\KIT\CORE" --out MANUALS             # one kit
python assembly_manual.py "…iam" --dry-run                            # print the steps only
python assembly_manual.py "…iam" --style lines --keep-drawing         # line art; keep the .idw to touch up
```

Per module it writes `<stem>.pdf` and `<stem>.manual.json` (parts list, steps with
directions, what was left out and why); each output folder gets a `manuals.json`
index. Existing PDFs are skipped unless `--overwrite`.

How the explosion is found (`explode_plan.py`, pure numpy, tested in
`tests/test_explode_plan.py`): every visible part is meshed, and per pair of parts
a depth map along ±X/±Y/±Z (and along the normal of a tilted plate, e.g. a mirror on a 45° seat) says whether one sits in front of the other. The module
is taken apart around its grounded part one round at a time (whatever nothing
blocks leaves along its free direction); reversed, that is the assembly order.
Screws, pins and washers (ISO/DIN/STD names) only count what sits in front of them
along their own axis, because their thread is modelled into a tap-drill hole.
Every part is then pulled out along its direction until its box clears what went
in before it, plus `--gap` (8 mm). Pages whose parts move sideways turn the module to the iso
corner they move towards, so nothing is pulled out behind what it goes into. Cable strands, hidden and virtual components
are listed but not drawn; stickers get one last step. A part that is stuck in
every direction (interfering CAD) is taken out where it is least stuck and the
step is marked `forced` in the JSON.

Nothing in the workspace is touched: each picture is a throw-away assembly of the
same part definitions (model states and appearance overrides carried over) saved
in a temp folder that is deleted afterwards (`--keep-drawing` keeps it with the
`.idw` beside the PDF). It runs in the open Inventor, invisibly, and leaves
`SilentOperation` as it found it; ~20 s for a 3-page module, ~50 s for 7 pages.

## Project builders (dvOPM, OpenRAMAN): CAD-new names

The assembly builders now live in their project repositories: `openuc2-opmsimulator`
(`build_opm_assembly.py`, `build_opm_holder_ipt.py`, pipeline in `OPM_CAD_README.md`) and
`openuc2-openraman` (`build_raman_assembly.py`). Both run in the miniforge `pyinventor` env with
a running Inventor and share `inventor_helpers.py` (one file, copied into each repo):

```bash
cd ..\openuc2-opmsimulator
python build_opm_assembly.py                 # INVENTOR\ASS - 9100 - OPMDVOPM - V04.iam + .stp + BOM JSON
python build_opm_assembly.py --n 1.56        # re-pose launch, stage, rays, sheet solid
cd ..\openuc2-openraman
python build_raman_assembly.py --all         # INVENTOR\ASS - 9200 - RAMAN - V04 - A|B|C.iam
```

They place the openUC2 parts and modules straight from `openUC2-CAD-new\workspace` (a library
path of the FRAME project) and keep Inventor's own occurrence names (`ASS - 2000 - CUB - V04:3`),
so the browser, the BOM and the GLB node names (see the naming contract in optikit-core) are the
CAD-new ones; each occurrence's purpose is an attribute (`uc2gen` / `role`). Generated parts get
CAD-new-style names with provisional 9xxx numbers, bought parts outside CAD-new `BUY - ...`,
reference geometry `REF - ...` outside the BOM. The scripts work on invisible documents, restore
`SilentOperation` and close only what they loaded.

Optics stay in cubes wherever possible (cubes first, then adapters). A CAD-new module that has to
face another way is rebuilt as a new assembly of the same CAD-new parts, turned inside its cube
(`occ_frame` / `turn_frame` in `inventor_helpers.py`): the dvOPM's fold mirror (`ASS - 9110`,
ASS-2020 turned) and lens cube (`ASS - 9111`, ASS-3011 turned); a part no module holds gets a
dedicated adapter in the cube (`ASS - 9112`, the camera in ASS-3011's master-insert sandwich).

COM lessons that these scripts encode: `Edge.StopVertex` (not EndVertex); a sketch on the
XZ origin plane has sketch-x = -model-X; distances, offsets and hole sizes accept strings
("30 mm" or a user-parameter name), which is what makes the features parametric; a coil
with the default rotation is a right-handed helix about its axis; hole features drilled
from a face plane with normal +Y need `kPositiveExtentDirection`; a multi-body STEP opens
as an assembly and cannot be saved as .ipt; browser names must be unique across sketches
and features; enum values (BOM structures, attribute value types) can be read from
`RxInventor.tlb` with `pythoncom.LoadTypeLib`.

## NEW FEATURES (v0.4.1):

### Assembly Image Creation
PyInventor now supports creating images from assembly files (IAM) with multiple perspectives and rendering options:

- **`iAssembly` Class** - Complete assembly document handling
- **Six Standard Perspectives** - Front, Back, Left, Right, Top, Bottom views + Isometric
- **Multiple Rendering Options** - Realistic, wireframe, shaded with edge control  
- **Batch Processing** - Process multiple assemblies automatically with `create_assembly_images_batch()`
- **Flexible Image Export** - PNG, JPG, BMP, TIF formats with custom resolutions
- **Organized Output** - Automatic folder organization and consistent naming

Example usage:
```python
# Single assembly image creation
assembly = iAssembly(path='C:\\assemblies', prefix='my_assembly.iam')
images = assembly.create_perspective_images(
    views=['front', 'back', 'left', 'right', 'top', 'bottom'],
    realistic=True, wireframe=False
)

# Batch process multiple assemblies
results = create_assembly_images_batch(
    assembly_folder='C:\\my_assemblies',
    output_folder='C:\\output_images',
    views=['front', 'back', 'left', 'right', 'top', 'bottom'],
    realistic=True
)
```

See `_Tutorial_Notebooks/assembly_image_example.py` and `ASSEMBLY_IMAGES.md` for complete examples and documentation.

### UC2 Grid Assembly Support
PyInventor now supports creating complex UC2 assemblies in grid patterns:

- **Grid-based Component Placement** - Place components in 50x50x55mm grids with simple coordinates
- **Flexible Rotations** - Apply rotations around X, Y, and Z axes
- **CSV Import/Export** - Define assemblies using CSV files for easy editing
- **Batch Operations** - Place multiple components with single function calls

Example usage:
```python
# Create UC2 assembly with grid spacing
assembly = iAssembly('UC2_Assembly.iam', units='metric')
assembly.set_grid_spacing(50.0, 50.0, 55.0)

# Place lens at origin, mirror at (50,0,0) with 90° rotation
assembly.place_component_at_grid('Assembly_cube_lens.iam', 0, 0, 0)
assembly.place_component_at_grid('Assembly_cube_mirror.iam', 1, 0, 0, rotation=(0, 90, 0))

assembly.save()
```

See `UC2_Grid_Documentation.md` and `_Tutorial_Notebooks/uc2_grid_example.py` for complete examples.

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
