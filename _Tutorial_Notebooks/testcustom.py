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

# Show or isolate specific body
body_target = part.get_body('BodyName')
part.show_only_body(body_target)

# Save and export STP
part.save()
part.save_copy_as(copy_name='BodyName.stp')
