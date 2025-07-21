import glob
from win32com.client import Dispatch, GetActiveObject, gencache, constants
import numpy as np
from numpy import cos, sin, pi, sqrt
import os
import copy
import xlwings as xw
import warnings
import re
import sys
import shutil
import json
from scipy.special import binom

'''

This version 4 of the inventor API for python creates a new com_obj class that is used for the initialization 
of the com port and the inventor object

Previous versions:

Verion 3 of the Inventor API for Python. This updates the drawing functionality, adds a revolve feature, 
sketch slots, sketch circles, object collection functionality, and generally streamlines the part creation process. 
Added a view manager that allows for view style and camera placement

Command list can be found at :
http://help.autodesk.com/view/INVNTOR/2019/ENU/

Written by: Andrew Oriani
9/21/2020

'''

def clear_excel_app_data():
    try:
        xw = gencache.EnsureDispatch('Excel.Application')
    except AttributeError:
        # Remove cache and try again.
        MODULE_LIST = [m.__name__ for m in sys.modules.values()]
        for module in MODULE_LIST:
            if re.match(r'win32com\.gen_py\..+', module):
                del sys.modules[module]
        shutil.rmtree(os.path.join(os.environ.get('LOCALAPPDATA'), 'Temp', 'gen_py'))
        xw = gencache.EnsureDispatch('Excel.Application')
    xw.Quit()


class com_obj(object):
    def __init__(self):
        '''
        Attempts to open inventor and setup com port
        '''
        try:
            self.invApp = GetActiveObject('Inventor.Application')
        except:
            self.invApp = Dispatch('Inventor.Application')
            self.invApp.Visible = True           

        self.mod = gencache.EnsureModule('{D98A091D-3A0F-4C3E-B36E-61F62068D488}', 0, 1, 0)
        self.invAppCom = self.mod.Application(self.invApp)
        
    
    def overwrite_file(self, path, prefix):  
        '''
        Overwrites existing file name
        '''
        if os.path.isfile(path+'\\'+prefix)==True:
            self.invApp.Documents.CloseAll()
            os.remove(path+'\\'+prefix)
        else:
            pass
        
    def new_part(self, prefix='', path=''):
        '''
        Generates new part document
        '''
        
        if prefix=='':
            self.invDoc = self.invApp.Documents.Add(constants.kPartDocumentObject, "", True)
        else:
            #check if input filename exists, if so, modify
            if os.path.isfile(path+'\\'+prefix)==True:
                try:
                    self.invDoc=self.invApp.Documents.Open(path+'\\'+prefix)
                except:
                    raise Exception('ERROR: Unable to open file, check filetype and if file is in target directory.')
                if self.invDoc.DocumentType==constants.kPartDocumentObject:
                    pass
                else:
                    raise Exception('ERROR: Document type is not part document')
            else:
                self.invDoc = self.invApp.Documents.Add(constants.kPartDocumentObject, "", True)
        
        # Casting Document to PartDocument
        self.invPartDoc = self.mod.PartDocument(self.invDoc)
        self.compdef = self.invPartDoc.ComponentDefinition
        
        #Opened document handle
        self.oDoc=self.invAppCom.ActiveDocument
        
        #create command manager
        self.cmdManager=self.invApp.CommandManager
        
        #Set transient geometry object
        self.tg=self.invApp.TransientGeometry
        self.trans_obj=self.invApp.TransientObjects
        
        #object view handle
        self.view=self.invApp.ActiveView
        
    def close_all_parts(self):
        self.invApp.Documents.CloseAll() 
    

                
class iPart(com_obj):
    def __init__(self, path='', prefix='', units='imperial', overwrite=True):
        
        self.overwrite=overwrite
        self.file_path=path
        self.f_name=prefix
        self.units=units
        
        try:
            self.thread_tables=glob.glob('C:\\Users\\Public\\Documents\\Autodesk\\Inventor 20*')[0]+'\\Design Data\\XLS\\en-US\\thread.xls'
        except:
            warnings.warn('Unable to locate thread tables, wont be able to create thread feature')
            self.thread_tables=[]
        #setup com with inventor
        super(iPart, self).__init__()
        
        if overwrite==True:
            self.overwrite_file(path, prefix)
        elif overwrite==False:
            pass
    
        #open part or setup new part
        self.new_part(prefix, path)

        #set document units
        self.set_units(units)
        
        
        #set file name and handle 
        self.f_name=prefix
        self.file_path=path
        
        #instantiate sketch, extrusion, and hole feature counters
        #sketch
        self.sketch_num=0
        self.sketch_list=[]
        #extrusion
        self.extrude_num=0
        self.extrude_list=[]
        #hole
        self.hole_num=0
        self.hole_list=[]
        #workplanes
        self.plane_num=0
        self.plane_list=[]
        
    
    class sketch:
        def __init__(self, sketch_obj, sketch_num, plane):
            self.sketch_num=sketch_num
            self.sketch_obj=sketch_obj
            self.plane=plane
        
        def edit(self):
            self.sketch_obj.Edit()
            
        def exit_edit(self):
            self.sketch_obj.ExitEdit()
            
    class extrusion:
        def __init__(self, extrude_obj, extrude_num):
            self.extrude_obj=extrude_obj
            self.extrude_num=extrude_num
    
    class planes:
        def __init__(self, plane_obj, plane_num):
            self.plane_obj=plane_obj
            self.plane_num=plane_num
    
    class hole:
        def __init__(self, hole_obj, hole_num):
            self.hole_obj=hole_obj
            self.hole_num=hole_num
            
    def set_visual_style(self, shaded=True, edges=True, hidden_edges=False, realistic=False):
        if realistic==False:
            if shaded==True:
                if edges==False:
                    val=8708
                else:
                    if hidden_edges==True:
                        val=8707
                    else:
                        val=8710
            else:
                if edges==True:
                    if hidden_edges==True:
                        val=8712
                    else:
                        val=8711
                else:
                    val=8706
        else:
            val=8709
        self.view.DisplayMode=val
        

    def f_check(self, path, f_name):
        if path[-1]!='\\':
            path=path+'\\'
        dirlist = glob.glob(path+'*'+f_name)
        if dirlist!=[]:
            return True
        elif dirlist==[]:
            return False
        
    def SP_check(self, obj):
        obj_type=self.API_type(obj)
        if obj_type=='SketchPoint':
            return True
        elif obj_type!='SketchPoint':
            return False
        else:
            raise Exception('ERROR: Object input is invalid')
            
    def API_type(self, obj):
        #check what the API object type is
        return str(type(obj)).split(' ')[-1].split('.')[-1].split('\'')[0]
    
    def object_check(self, obj):
        #checks if obj is valid Inventor Object
        try:
            return str(obj).split(' ')[1]+' '+str(obj).split(' ')[2]
        except:
            pass
        try:
            return str(type(obj)).split(' ')[1]+' '+str(type(obj)).split(' ')[2]
        except:
            pass
        
        return self.API_type(obj)
            
    def copy_file_ext_types(self):
        return ['stp', 'stl', 'step', 'stpz', 'ste', 'ipt', 'igs', 'ige', 'iges']
            
    def save(self, file_path='', file_name=''):
        #save file in requisite path, if copy flag is set it saves a numbered copy of the original file
        if file_name=='' and self.f_name!='':
            file_name=self.f_name
        elif self.f_name=='':
            raise Exception('ERROR: Need filename for .ipt file')
        if file_path=='' and self.file_path!='':
            file_path=self.file_path
        elif file_path=='' and self.file_path=='':
            file_path=os.getcwd()
            
        check=self.f_check(file_path, file_name)
        
        if check==True:
            file_name=get_next_filename(file_path, file_name)
        else:
            pass
            
        full_path=file_path+'\\'+file_name
        
        if os.path.isfile(full_path)==True and self.overwrite==False:
            self.invDoc.Save()
        else:
            self.invDoc.SaveAs(full_path, SaveCopyAs=False)
       
        return full_path
            
    def save_copy_as(self,  copy_name='', file_path='', copy_as=''):
        
        suffix=copy_as
        
        if file_path=='' and self.file_path!='':
            file_path=self.file_path
        elif file_path=='' and self.file_path=='':
            file_path=os.getcwd()
        
        if copy_name=='' and self.f_name!='':
            copy_name=self.f_name
        else:
            pass
        
        file_type=copy_name.split('.')[-1]
        if suffix!='' and file_type!=suffix:
            if suffix in self.copy_file_ext_types() and file_type in self.copy_file_ext_types():
                copy_name=copy_name.split('.')[0]+'.'+suffix
            else:
                raise Exception('ERROR: Not a valid filetype, must be stp, stl, ipt, or igs file extension') 
        else:
            pass
        
        if self.f_check(file_path, copy_name)==True:
            copy_name=get_next_filename(file_path, copy_name)
        else:
            pass
        
        full_path=file_path+'\\'+copy_name
        
        self.invDoc.SaveAs(full_path, SaveCopyAs=True)
        
        print('File successfully copied as: %s'%(full_path))
        
        return full_path 
        

    def set_parameter(self, param_name, param_value):
        """
        Create or update a user parameter in the active part document.
        """
        params = self.invPartDoc.ComponentDefinition.Parameters
        try:
            user_param = params.UserParameters.Item(param_name)
            user_param.Expression = str(param_value)
        except:
            # If the parameter doesn't exist, create it as a length-type parameter
            user_param = params.UserParameters.AddByValue(
                param_name,
                self.unit_conv(param_value),
                self.invDoc.UnitsOfMeasure.LengthUnits
            )
        return user_param

    def list_bodies(self):
        """
        Returns a list of all body names in the current part.
        """
        try:
            bodies = self.compdef.SurfaceBodies
            body_names = []
            for i in range(1, bodies.Count + 1):
                body_names.append(bodies.Item(i).Name)
            return body_names
        except Exception as e:
            print(f"Error accessing SurfaceBodies: {e}")
            # Fallback: try accessing solid bodies if surface bodies don't work
            try:
                solid_bodies = self.compdef.SolidBodies
                body_names = []
                for i in range(1, solid_bodies.Count + 1):
                    body_names.append(solid_bodies.Item(i).Name)
                return body_names
            except Exception as e2:
                print(f"Error accessing SolidBodies: {e2}")
                return []

    def debug_info(self):
        """
        Returns debug information about the iPart object to help troubleshoot issues.
        """
        info = {
            'has_compdef': hasattr(self, 'compdef'),
            'compdef_type': type(self.compdef).__name__ if hasattr(self, 'compdef') else 'None',
            'methods': [method for method in dir(self) if not method.startswith('_') and callable(getattr(self, method))],
            'has_surface_bodies': False,
            'has_solid_bodies': False,
            'surface_body_count': 0,
            'solid_body_count': 0
        }
        
        if hasattr(self, 'compdef'):
            try:
                surface_bodies = self.compdef.SurfaceBodies
                info['has_surface_bodies'] = True
                info['surface_body_count'] = surface_bodies.Count
            except:
                pass
                
            try:
                solid_bodies = self.compdef.SolidBodies
                info['has_solid_bodies'] = True
                info['solid_body_count'] = solid_bodies.Count
            except:
                pass
        
        return info

    def get_body(self, body_name):
        """
        Returns a surface or solid body by matching its Name property.
        """
        # In the Inventor API, both solids and surfaces are stored in 'SurfaceBodies'
        bodies = self.compdef.SurfaceBodies
        for i in range(1, bodies.Count + 1):
            body = bodies.Item(i)
            if body.Name == body_name:
                return body
        raise ValueError(f"No body found with name '{body_name}'")

    def show_only_body(self, body_or_name):
        """
        Hide all bodies except the specified one.
        
        Args:
            body_or_name: Either a body object returned by get_body() or a string with the body name
        """
        if isinstance(body_or_name, str):
            target_body = self.get_body(body_or_name)
        else:
            target_body = body_or_name
            
        bodies = self.compdef.SurfaceBodies
        for i in range(1, bodies.Count + 1):
            body = bodies.Item(i)
            if body.Name == target_body.Name:
                body.Visible = True
            else:
                body.Visible = False

    def show_all_bodies(self):
        """
        Make all bodies visible.
        """
        bodies = self.compdef.SurfaceBodies
        for i in range(1, bodies.Count + 1):
            body = bodies.Item(i)
            body.Visible = True

    def export_body_as(self, body_or_name, copy_name='', file_path=''):
        """
        Export a specific body as STP file.
        
        Args:
            body_or_name: Either a body object returned by get_body() or a string with the body name
            copy_name: Name for the exported file (will add .stp extension if not present)
            file_path: Directory path for the exported file (uses current file path if empty)
        """
        if isinstance(body_or_name, str):
            target_body = self.get_body(body_or_name)
            body_name = body_or_name
        else:
            target_body = body_or_name
            body_name = target_body.Name
            
        # Set default file name if not provided
        if copy_name == '':
            copy_name = f"{body_name}.stp"
        elif not copy_name.endswith('.stp'):
            copy_name = f"{copy_name}.stp"
            
        # Set default file path if not provided
        if file_path == '':
            if self.file_path != '':
                file_path = self.file_path
            else:
                file_path = os.getcwd()
                
        # Ensure path ends with backslash
        if file_path[-1] != '\\':
            file_path = file_path + '\\'
            
        # Check if file already exists and get next available name
        if self.f_check(file_path, copy_name):
            base_name = copy_name.replace('.stp', '')
            copy_name = get_next_filename(file_path, base_name, '.stp')
            
        full_path = file_path + copy_name
        
        # Hide all other bodies, show only target body
        original_visibility = {}
        bodies = self.compdef.SurfaceBodies
        for i in range(1, bodies.Count + 1):
            body = bodies.Item(i)
            original_visibility[body.Name] = body.Visible
            if body.Name == target_body.Name:
                body.Visible = True
            else:
                body.Visible = False
        
        try:
            # Export the part (with only the target body visible)
            self.invDoc.SaveAs(full_path, SaveCopyAs=True)
            print(f'Body "{body_name}" successfully exported as: {full_path}')
        finally:
            # Restore original visibility
            for i in range(1, bodies.Count + 1):
                body = bodies.Item(i)
                body.Visible = original_visibility[body.Name]
                
        return full_path


    def set_units(self, units='imperial'):
        if units=='imperial':
            angle=constants.kDegreeAngleUnits
            length=constants.kInchLengthUnits
        elif units=='metric':
            angle=constants.kRadianAngleUnits
            length=constants.kMillimeterLengthUnits
        else:
            raise Exception('ERROR: Invalid units input, must be imperial or metric')
        self.invDoc.UnitsOfMeasure.LengthUnits=length
        self.invDoc.UnitsOfMeasure.AngleUnits=angle
        self.invDoc.Rebuild
        self.units=units    
        
    def unit_conv(self, val_in):
        units=self.units
        if units=='imperial':
            mult=2.54
        elif units=='metric':
            mult=.1

        if type(val_in)==np.float64 or type(val_in)==float or type(val_in)==int:
            return mult*val_in
        elif type(val_in)!=list or type(val_in)==tuple:
            return tuple(mult*np.array(val_in))
        elif type(val_in)==list:
            if type(val_in[0])==tuple and len(val_in[0])==2:
                for I, vals in enumerate(val_in):
                    vals=list(vals)
                    vals[0]=vals[0]*mult
                    vals[1]=vals[1]*mult
                    val_in[I]=tuple(vals)
            else:
                raise Exception('ERROR: input list not a tuples or len is not equal to 2')
            return val_in 
        
    def inv_unit_conv(self, val_in):
        units=self.units
        if units=='imperial':
            mult=2.54
        elif units=='metric':
            mult=.1

        if type(val_in)==np.float64 or type(val_in)==float or type(val_in)==int:
            return val_in/mult
        elif type(val_in)!=list or type(val_in)==tuple:
            return tuple(np.array(val_in)/mult)
        elif type(val_in)==list:
            if type(val_in[0])==tuple and len(val_in[0])==2:
                for I, vals in enumerate(val_in):
                    vals=list(vals)
                    vals[0]=vals[0]/mult
                    vals[1]=vals[1]/mult
                    val_in[I]=tuple(vals)
            else:
                raise Exception('ERROR: input list not a tuples or len is not equal to 2')
            return val_in 
            
    def ang_conv(self, val_in):
        units=self.units
        if units=='imperial':
            mult=np.pi/180
        elif units=='metric':
            mult=1
        return val_in*mult
    
    def close(self, save=True):
        #close the inventor part document
        if save==True:
            self.invPartDoc.Close(SkipSave=False)
        elif save==False:
            self.invPartDoc.Close(SkipSave=True)
        else:
            raise Exception('ERROR: Invalid save input, must be boolean')
            
    def thread_gen(self, dia, pitch, thread_type='unified', thread_class=''):
        
        #open native inventor thread tables with thread designators

        if self.thread_tables==[]:
            raise Exception('ERROR: Unable to find native inventor thread tables.')

        try:
            thread_tables_path=self.thread_tables
            try:
                xw.App(visible=False)
            except:
                clear_excel_app_data()
                xw.App(visible=False)

            thread_tables=xw.Book(thread_tables_path)

            if thread_type=='unified' or thread_type=='imperial':
                thread_type='ANSI Unified Screw Threads'
                split_ele='-'
                if thread_class=='':
                    thread_class='2B'
                else:
                    pass
            elif thread_type=='metric':
                dia='M'+dia
                split_ele='x'
                thread_type='ANSI Metric M Profile'
                if pitch.split('.')[0]=='':
                    pitch='0'+pitch
                else:
                    pass
                if thread_class=='':
                    thread_class='6H'
                else:
                    pass

            thread_sheet=thread_tables.sheets[thread_type]
            thread_des=thread_sheet.api.UsedRange.Find('Thread Designation').GetAddress()
        except:
            raise Exception('ERROR: Unable to open native inventor thread tables.')

        #conduct search of thread tables for single listing
        class_col='N'

        row_col=thread_des.split('$')[1::]
        row_start=int(row_col[1])+1
        row=row_start
        col=row_col[0]
        while thread_sheet.range('%s%s'%(col, str(row))).value!=None:
            row+=1
            pass

        tap_list=thread_sheet.range('%s%s:%s%s'%(col, str(row_start), col, str(row-1))).value
        class_list=thread_sheet.range('%s%s:%s%s'%(class_col, str(row_start), class_col, str(row-1))).value
        
        #make sure to fully close table
        thread_tables.close()
        
        dia_indices = [i for i, elem in enumerate(tap_list) if dia in elem.split(split_ele)[0][0:len(dia)] and len(elem.split(split_ele)[0])==len(dia)]

        if dia_indices==[]:
            raise Exception('ERROR: Invalid value for hole diameter')
        else:
            pass

        dia_vals=[np.array(tap_list)[dia_indices].tolist(), dia_indices]

        pitch_indices=[dia_indices[i] for i, elem in enumerate(dia_vals[0]) if pitch in elem.split(split_ele)[1]]

        if pitch_indices==[]:
            raise Exception('ERROR: Invalid value for thread pitch')
        else:
            pass

        thread_input=[]
        for inds in pitch_indices:
            thread_input.append([tap_list[inds], class_list[inds]])

        thread_input=[thread_input[1][i] for i, elem in enumerate(thread_input) if elem[1]!=None and thread_class in elem[1]]

        if thread_input==[] or len(thread_input)>1:
            raise Exception('ERROR: Invalid thread class')

        return thread_input[0], thread_type, thread_class
            
    def pick(self, feature='planes'):
        feature_vals={'points':{'msg': 'Pick Points', 'enum': constants.kAllPointEntities},
                 'planes':{'msg': 'Pick Planes', 'enum': constants.kWorkPlaneFilter},
                 'linear':{'msg': 'Pick Line Elements', 'enum': constants.kAllLinearEntities}, 
                 'circular':{'msg': 'Pick Circular Elements', 'enum': constants.kAllCircularEntities},
                 'sketch':{'msg': 'Pick Sketch', 'enum': constants.kSketchObjectFilter},
                 'face':{'msg': 'Pick Face', 'enum': constants.kPartFacePlanarFilter}
            }
        if feature in feature_vals.keys():
            pass
        else:
            raise Exception('ERROR: Invalid feature descriptor (points, planes, linear, circular, sketch) elements')
        
        enum=feature_vals[feature]['enum']
        msg=feature_vals[feature]['enum']
        return self.cmdManager.Pick(enum, msg)
        
    def pick_point(self):
        point=self.pick(feature='points')
        return point
        
    def pick_plane(self):
        plane=self.pick(feature='planes')
        return plane
        
    def pick_sketch(self):
        sketch=self.pick(feature='sketch')
        return sketch
        
    def pick_line(self):
        return self.pick(feature='linear')

    
    def pick_circle(self):
        return self.pick(feature='circular')

    
    def pick_face(self):
        return self.pick(feature='face')
        
        
    def copy_sketch(self, sketch):
        sketch_obj, sketch_num, _=self.sketch_test(sketch)
        if self.API_type(sketch_obj)=='PlanarSketch':
            pass
        else:
            raise Exception('ERROR: Not valid sketch type')
        sketchCopy=self.compdef.Sketches.Item(sketch_num)
        self.oDoc.SelectSet.Clear()
        self.oDoc.SelectSet.Select(sketchCopy)
        self.copy()
        self.paste()
    
    def sketch_test(self, sketch):
        try:
            sketch_obj=sketch.sketch_obj
            sketch_num=sketch.sketch_num
            plane=sketch.plane
            return sketch_obj, sketch_num, plane
        except:
            raise Exception('ERROR: Invalid target sketch object')
            
        
    def copy_paste_sketch(self, target_sketch, sketch):
        sketch_obj, sketch_num=self.sketch_test(target_sketch)
        self.copy_sketch(sketch)
        sketch_obj.Edit()
        self.paste()
        sketch_obj.ExitEdit()
        
    def copy(self):
        copy_def=self.cmdManager.ControlDefinitions.Item("AppCopyCmd")
        copy_def.Execute()
        
    def paste(self):
        paste_def=self.cmdManager.ControlDefinitions.Item("AppPasteCmd")
        paste_def.Execute()
    
        
    def add_workplane(self, plane='xy', offset=None):
        if offset==None:
            offset=0
        else:
            offset=self.unit_conv(offset)
        if type(plane)==str:
            if plane=='xy':
                plane='XY Plane'
            elif plane=='xz':
                plane='XZ Plane'
            elif plane=='yz':
                plane='YZ Plane'
            else:
                raise Exception('ERROR: Invalid plane desciptor, (xy, xz, yz)')
            plane=self.compdef.WorkPlanes.Item(plane)
        elif self.API_type(plane)=='Face':
            pass
        else:
            raise Exception('ERROR: Invalid input, must be face/planar object or coordinate system (xy, xz, yz)')
        return self.add_offset_workplane(plane, offset)
            
    def add_offset_workplane(self, plane, offset, construction=True):
        self.plane_num+=1
        self.plane_list.append(self.plane_num)
        plane_obj=self.compdef.WorkPlanes.AddByPlaneAndOffset(plane, offset, construction)
        return self.planes(plane_obj, self.plane_num)
    
    def new_sketch(self, plane):
        self.sketch_num+=1
        self.sketch_list.append(self.sketch_num)
        return self.sketch(self.compdef.Sketches.Add(plane.plane_obj), self.sketch_num, plane)
    
    def delete_sketch(self, sketch):
        sketch_obj, sketch_num, _=self.sketch_test(sketch)
        self.sketch_list.remove(sketch_num)
        sketch_obj.Delete()
    
    def two_point_centered_rect(self, sketch, center, corner):
        sketch=sketch.sketch_obj
        rect_obj=sketch.SketchLines.AddAsTwoPointCenteredRectangle(self.point(center), self.point(corner))
        rect_obj_coll=self.new_obj_collection()
        return rect_obj_coll.Add(rect_obj)

    
    def sketch_point(self, sketch, pos):
        sketch_obj=sketch.sketch_obj
        return sketch_obj.SketchPoints.Add(self.point(pos))

    def sketch_point_coll(self, sketch, pos):
        sketch_obj=sketch.sketch_obj
        if pos==[] or type(pos)!=list:
            raise Exception('ERROR: Must be a list of tuples representing points')
        else:
            pass
        points=[]
        for coords in pos:
            points.append(self.sketch_point(sketch, coords))
        return self.create_obj_collection(points)
    
    def two_point_rect(self, sketch, corner_1, corner_2):
        rect_obj=sketch.SketchLines.AddAsTwoPointRectangle(self.point(corner_1), self.point(corner_2))
        rect_obj_coll=self.new_obj_collection()
        return rect_obj_coll.Add(rect_obj)
    
    def sketch_circle(self, sketch, center, radius):
        sketch=sketch.sketch_obj
        circle=sketch.SketchCircles.AddByCenterRadius(self.point(center), self.unit_conv(radius))
        circle_obj=self.new_obj_collection()
        circle_obj.Add(circle)
        return circle_obj
    
    def sketch_slot(self, sketch, start, end, width, overall_length=False):
        sketch=sketch.sketch_obj
        if overall_length==True:
            slot=sketch.AddStraightSlotByOverall(self.point(start), self.point(end), self.unit_conv(width))
        elif overall_length==False:
            slot=sketch.AddStraightSlotByCenterToCenter(self.point(start), self.point(end), self.unit_conv(width))
        
        slot_obj=self.new_obj_collection()
        for I in range(1,slot.Count):
            slot_obj.Add(slot.Item(I))
            
        return slot_obj
    
    def sketch_center_slot(self, sketch, center, end, width):
        sketch=sketch.sketch_obj
        slot=sketch.AddStraightSlotBySlotCenter(self.point(center), self.point(end), self.unit_conv(width))
        
        slot_obj=self.new_obj_collection()
        for I in range(1,slot.Count):
            slot_obj.Add(slot.Item(I))
        return slot_obj
            
    def point(self, pos):
        self.tg=self.invApp.TransientGeometry
        if self.SP_check(pos)==False:
            if type(pos)!=tuple and type(pos)!=list:
                raise Exception('ERROR: Point position must be list of form [x,y]')
            elif len(pos)!=2:
                raise Exception('ERROR: Point position must be len=2 list')
            else:
                return self.tg.CreatePoint2d(self.unit_conv(pos[0]), self.unit_conv(pos[1]))
        elif self.SP_check(pos)==True:
                return pos
        else:
            raise Exception('Position must be object endpoint or [x,y] position')
            
    def undo(self):
        undoDef=self.cmdManager.ControlDefinitions.Item("AppUndoCmd")
        undoDef.Execute()
            
    def extrude(self, sketch, thickness, obj_collection=None, direction='positive', operation='join'):
        sketch_obj, sketch_num, _=self.sketch_test(sketch)
        sketch=sketch_obj
        self.extrude_num+=1
        self.extrude_list.append(self.extrude_num)
        if operation=='join':
            op=constants.kJoinOperation
        elif operation=='intersect':
            op=constants.kIntersectOperation
        elif operation=='cut':
            op=constants.kCutOperation
        elif operation=='new_form':
            op=constants.kNewBodyOperation
        elif operation=='surface':
            op=constants.kSurfaceOperation
        else:
            raise Exception('ERROR: Operation must be either join, cut, intersect, new_form, or surface.')
        
        if direction=='positive':
            extrude_dir=constants.kPositiveExtentDirection
        elif direction=='negative':
            extrude_dir=constants.kNegativeExtentDirection
        elif direction=='symmetric':
            extrude_dir=constants.kSymmetricExtentDirection
        else:
            raise Exception('ERROR: Extrude direction must be positive, negative, or symmetric')
        if obj_collection==None:
            profile=sketch.Profiles.AddForSolid()
        elif self.API_type(obj_collection)=='ObjectCollection':
            profile=sketch.Profiles.AddForSolid(False, obj_collection)
        else:
            raise Exception('ERROR: Invalid object collection type, must be API type ObjectCollection')
        
        extrudeDef=self.compdef.Features.ExtrudeFeatures.CreateExtrudeDefinition(profile, op)
        extrudeDef.SetDistanceExtent(self.unit_conv(thickness), extrude_dir)
        return self.compdef.Features.ExtrudeFeatures.Add(extrudeDef)
    
    def revolve_full(self, sketch, axis='x', obj_collection=None, operation='join'):
        sketch_obj, sketch_num, _=self.sketch_test(sketch)
        sketch=sketch_obj
        if type(axis)==str:
            if axis=='x':
                axis=self.compdef.WorkAxes.Item(1)
            elif axis=='y':
                axis=self.compdef.WorkAxes.Item(2)
            elif axis=='z':
                axis=self.compdef.WorkAxes.Item(3)
            else:
                raise Exception("ERROR: Invalid axis, must be x, y, z")
        elif self.API_type(axis)=='SketchLine':
            pass
        else:
            raise Exception('ERROR: Revolve axis must be SketchLine object or cardinal axis')
        
        if operation=='join':
            op=constants.kJoinOperation
        elif operation=='intersect':
            op=constants.kIntersectOperation
        elif operation=='cut':
            op=constants.kCutOperation
        elif operation=='new_form':
            op=constants.kNewBodyOperation
        elif operation=='surface':
            op=constants.kSurfaceOperation
        else:
            raise Exception('ERROR: Operation must be either join, cut, intersect, new_form, or surface.')
        
    
        if obj_collection==None:
            profile=sketch.Profiles.AddForSolid()
        elif self.API_type(obj_collection)=='ObjectCollection':
            profile=sketch.Profiles.AddForSolid(False, obj_collection)
        
        revolveDef=self.compdef.Features.RevolveFeatures.AddFull(profile, axis, op)
        return revolveDef
    

    def revolve_ang(self, sketch, angle, axis='x', obj_collection=None, direction='positive', operation='join'):
        sketch_obj, sketch_num, _=self.sketch_test(sketch)
        sketch=sketch_obj
        if type(axis)==str:
            if axis=='x':
                axis=self.compdef.WorkAxes.Item(1)
            elif axis=='y':
                axis=self.compdef.WorkAxes.Item(2)
            elif axis=='z':
                axis=self.compdef.WorkAxes.Item(3)
            else:
                raise Exception("ERROR: Invalid axis, must be x, y, z")
        elif self.API_type(axis)=='SketchLine':
            pass
        else:
            raise Exception('ERROR: Revolve axis must be SketchLine object or cardinal axis')
        
        if operation=='join':
            op=constants.kJoinOperation
        elif operation=='intersect':
            op=constants.kIntersectOperation
        elif operation=='cut':
            op=constants.kCutOperation
        elif operation=='new_form':
            op=constants.kNewBodyOperation
        elif operation=='surface':
            op=constants.kSurfaceOperation
        else:
            raise Exception('ERROR: Operation must be either join, cut, intersect, new_form, or surface.')
        
        if direction=='positive':
            extrude_dir=constants.kPositiveExtentDirection
        elif direction=='negative':
            extrude_dir=constants.kNegativeExtentDirection
        elif direction=='symmetric':
            extrude_dir=constants.kSymmetricExtentDirection
        else:
            raise Exception('ERROR: Extrude direction must be positive, negative, or symmetric')
    
        if obj_collection==None:
            profile=sketch.Profiles.AddForSolid()
        elif self.API_type(obj_collection)=='ObjectCollection':
            profile=sketch.Profiles.AddForSolid(False, obj_collection)
        
        revolveDef=self.compdef.Features.RevolveFeatures.AddByAngle(profile, axis, self.ang_conv(angle), extrude_dir,  op)
        return revolveDef
    
    def circular_feature_pattern(self, obj_collection, count, angle, axis='x', axis_dir=True, fit_within_ang=True):
        if type(axis)==str:
            if axis=='x':
                axis=self.compdef.WorkAxes.Item(1)
            elif axis=='y':
                axis=self.compdef.WorkAxes.Item(2)
            elif axis=='z':
                axis=self.compdef.WorkAxes.Item(3)
            else:
                raise Exception("ERROR: Invalid axis, must be x, y, z")
        elif self.API_type(axis)=='WorkAxis':
            pass
        elif self.API_type(axis)=='SketchLine':
            axis=self.work_axes_from_line(axis)
        else:
            raise Exception('ERROR: Revolve axis must be WorkAxis object or cardinal axis')
            
        if self.API_type(obj_collection)!='ObjectCollection':
            raise Exception('ERROR: obj_collection must be of object collection type (see new_obj_collection)')
        else:
            pass
            
        if self.units=='imperial':
            rot_angle='%.3f deg'%angle
        elif self.units=='radian':
            rot_angle='%.3f rad'%angle
        pat_def=self.compdef.Features.CircularPatternFeatures.CreateDefinition(obj_collection, axis, axis_dir, count, rot_angle, fit_within_ang)
        pat_feat=self.compdef.Features.CircularPatternFeatures.AddByDefinition(pat_def)
        pat_feat.SetEndOfPart(True)
        pat_feat.Parameters.Item(1).Expression=rot_angle
        pat_feat.SetEndOfPart(False)
        return pat_feat
    
    def rectangular_feature_pattern(self, obj_collection, count, spacing, axis='x', direction='positive', fit_within_len=False):
        if type(axis)==str:
            if axis=='x':
                axis=self.compdef.WorkAxes.Item(1)
            elif axis=='y':
                axis=self.compdef.WorkAxes.Item(2)
            elif axis=='z':
                axis=self.compdef.WorkAxes.Item(3)
            else:
                raise Exception("ERROR: Invalid axis, must be x, y, z")    
        elif self.API_type(axis)=='WorkAxis':
            pass
        else:
            raise Exception('ERROR: Revolve axis must be WorkAxis object or cardinal axis')
            
        if self.API_type(obj_collection)!='ObjectCollection':
            raise Exception('ERROR: obj_collection must be of object collection type (see new_obj_collection)')
        else:
            pass
          
        if fit_within_len==False:
            space_type=constants.kDefault
        elif fit_within_len==True:
            space_type=constants.kFitted
        else:
            raise Exception('ERROR: fit within length must be boolean')
            
        if direction=='positive':
            direction=True
        elif direction=='negative':
            direction=False
        else:
            raise Exception('ERROR: direction must be positive of negative')
        
        pat_def=self.compdef.Features.RectangularPatternFeatures.CreateDefinition(obj_collection, axis, direction, int(count), self.unit_conv(spacing), space_type)
        pat_feat=self.compdef.Features.RectangularPatternFeatures.AddByDefinition(pat_def)
        return pat_feat
        
    def mirror_objects(self, obj_collection, mirror_plane='xy', compute_type='identical'):
        if type(mirror_plane)==str:
            if mirror_plane=='xy':
                mirror_plane='XY Plane'
            elif mirror_plane=='xz':
                mirror_plane='XZ Plane'
            elif mirror_plane=='yz':
                mirror_plane='YZ Plane'
            else:
                raise Exception('ERROR: Invalid plane desciptor, (xy, xz, yz)')
            mirror_plane=self.compdef.WorkPlanes.Item(mirror_plane)

        elif self.API_type(mirror_plane)=='planes':
            mirror_plane=mirror_plane.plane_obj
            pass
        elif self.API_type(mirror_plane)=='WorkPlane':
            pass
        else:
            raise TypeError('ERROR: Invalid plane desciptor, (xy, xz, yz) or Inventor plane object')

        if compute_type=='identical':
            comp_type=constants.kIdenticalCompute
        elif compute_type=='optimized':
            comp_type=constants.kOptimizedCompute
        elif compute_type=='adjusted':
            comp_type=constants.kAdjustToModelCompute
        else:
            raise Exception('Compute-type must be identical, optimized, or adjusted...may need to play around with.')

        if self.API_type(obj_collection)!='ObjectCollection':
            raise TypeError('ERROR: obj_collection must be of object collection type (see new_obj_collection)')
        else:
            pass
        mirror_def=self.compdef.Features.MirrorFeatures.CreateDefinition(obj_collection, mirror_plane, 47361)
        return self.compdef.Features.MirrorFeatures.AddByDefinition(mirror_def)

    def fixed_work_point(self, sketch, pos, construction=True):
        return self.compdef.WorkPoints.AddByPoint(self.sketch_point(sketch, pos), construction)
    
    def center_arc_line(self, sketch, center, radius, start_ang, sweep_ang):
        sketch_obj, _, _=self.sketch_test(sketch)
        center_pt=self.point(center)
        radius=self.unit_conv(radius)
        start_ang=self.ang_conv(start_ang)
        sweep_ang=self.ang_conv(sweep_ang)
        arc_lines=sketch_obj.SketchArcs
        return arc_lines.AddByCenterStartSweepAngle(center_pt, radius, start_ang, sweep_ang)
    
    def work_axes_2_pt(self, sketch, start_pt, end_pt):
        return self.compdef.WorkAxes.AddByTwoPoints(self.sketch_point(sketch, start_pt), self.sketch_point(sketch, end_pt))
    
    def work_axes_from_line(self, line):
        if self.API_type(line)!='SketchLine':
            raise TypeError('Line must be SketchLine object')
        return self.compdef.WorkAxes.AddByLine(line)


    def arc_line(self, sketch, center, start_pt, end_pt, flip=True):
        sketch_obj, _, _=self.sketch_test(sketch)
        center_pt=self.point(center)
        start_pt=self.point(start_pt)
        end_pt=self.point(end_pt)
        arc_lines=sketch_obj.SketchArcs
        return arc_lines.AddByCenterStartEndPoint(center_pt, start_pt, end_pt, flip)
    
    def new_hole(self,sketch, pos, dia, depth, direction='negative', FlatBottom=False, BottomTipAngle=None):
        sketch_obj, sketch_num, plane=self.sketch_test(sketch)
        dia=self.unit_conv(dia)
        depth=self.unit_conv(depth)
        self.hole_num+=1
        self.hole_list.append(self.hole_num)
        
        if direction=='positive':
            extent_dir=constants.kPositiveExtentDirection
        elif direction=='negative':
            extent_dir=constants.kNegativeExtentDirection
        elif direction=='symmetric':
            extent_dir=constants.kSymmetricExtentDirection
        else:
            raise Exception('ERROR: Extrude direction must be positive, negative, or symmetric')
        
        if type(pos)==tuple:
            work_point=self.fixed_work_point(sketch, pos)
            hole_placement=self.compdef.Features.HoleFeatures.CreatePointPlacementDefinition(work_point, plane.plane_obj)
        elif type(pos)==list and pos!=[]:
            points_coll=self.sketch_point_coll(sketch, pos)
            hole_placement=self.compdef.Features.HoleFeatures.CreateSketchPlacementDefinition(points_coll)
            
        hole_feature=self.compdef.Features.HoleFeatures.AddDrilledByDistanceExtent(hole_placement, dia, depth, extent_dir, FlatBottom, BottomTipAngle)    
        return hole_feature
    
    def new_threaded_hole(self, sketch, pos, depth, thread_dia, thread_pitch, thread_depth, direction='negative', right_handed=True, FlatBottom=False, BottomTipAngle=None):
        sketch_obj, sketch_num, plane=self.sketch_test(sketch)
        depth=self.unit_conv(depth)
        thread_depth=self.unit_conv(thread_depth)
        self.hole_num+=1
        self.hole_list.append(self.hole_num)
        
        if direction=='positive':
            extent_dir=constants.kPositiveExtentDirection
        elif direction=='negative':
            extent_dir=constants.kNegativeExtentDirection
        elif direction=='symmetric':
            extent_dir=constants.kSymmetricExtentDirection
        else:
            raise Exception('ERROR: Extrude direction must be positive, negative, or symmetric')
        
        if thread_dia[0].upper()=='M':
            thread_type='metric'
            thread_dia=thread_dia[1::]
        else:
            thread_type='unified'
            
        if thread_depth>=depth:
            full_tap_depth=True
            thread_depth=depth
        else:
            full_tap_depth=False
            
        thread_type, thread_dsig, thread_class=self.thread_gen(dia=thread_dia, pitch=thread_pitch, thread_type=thread_type, thread_class='')
    
        hole_tap_info=self.compdef.Features.HoleFeatures.CreateTapInfo(right_handed, thread_dsig, thread_type, thread_class, full_tap_depth, thread_depth)
        
        if type(pos)==tuple:
            work_point=self.fixed_work_point(sketch, pos)
            hole_placement=self.compdef.Features.HoleFeatures.CreatePointPlacementDefinition(work_point, plane.plane_obj)
        elif type(pos)==list and pos!=[]:
            points_coll=self.sketch_point_coll(sketch, pos)
            hole_placement=self.compdef.Features.HoleFeatures.CreateSketchPlacementDefinition(points_coll)
            
        hole_feature=self.compdef.Features.HoleFeatures.AddDrilledByDistanceExtent(hole_placement, hole_tap_info, depth, extent_dir, FlatBottom, BottomTipAngle)    
        return hole_feature
            
    def sketch_spline(self, sketch, points):
        sketch=sketch.sketch_obj
        pt_coll=self.new_obj_collection()
        pts=[self.point(pt) for pt in points]
        for pt in pts:
            pt_coll.Add(pt)
        spline=sketch.SketchSplines.Add(pt_coll)
        return spline

    def sketch_line(self, sketch, start, end):
        sketch_obj, _, _=self.sketch_test(sketch)
        lines=sketch_obj.SketchLines
        return lines.AddByTwoPoints(self.point(start), self.point(end))
    
    def poly_lines(self, sketch, points):
        sketch_obj, _, _=self.sketch_test(sketch)
        points=self.unit_conv(points)
        if len(points)<3:
            raise Exception('ERROR: Points array must be len=3 or greater')
        else:
            pass
        
        if points[0]!=points[-1]:
            points.append(points[0])
        
        start=points[0]
        start_pt=self.tg.CreatePoint2d(start[0], start[1])
        lines=[]
        self.tg=self.invApp.TransientGeometry
        line_obj=sketch_obj.SketchLines
        for pt in points[1:-1]:
            stop_pt=self.tg.CreatePoint2d(pt[0], pt[1])
            lines.append(line_obj.AddByTwoPoints(start_pt, stop_pt))
            start_pt=lines[-1].EndSketchPoint
            
        lines.append(line_obj.AddByTwoPoints(start_pt, lines[0].StartSketchPoint))
        
        poly_line_coll=self.new_obj_collection()
        for vals in lines:
            poly_line_coll.Add(vals)
            
        return poly_line_coll
    
    def new_obj_collection(self):
        trans_obj=self.invApp.TransientObjects
        return trans_obj.CreateObjectCollection()
    
    def create_obj_collection(self, obj):
        new_coll=self.new_obj_collection()
        if type(obj)==list:
            for objs in obj:
                obj_check=self.object_check(objs)
                if obj_check!='Inventor Object': 
                    if obj_check!='ObjectCollection':
                        raise Exception('ERROR: object not Inventor Object or Object Collection')
                    else:
                        pass
                else:
                    if obj_check!='ObjectCollection':
                        new_coll.Add(objs)
                    else:
                        pass
        else:
            obj_check=self.object_check(obj)
            if obj_check!='Inventor Object': 
                    if obj_check!='ObjectCollection':
                        raise Exception('ERROR: object not Inventor Object or Object Collection')
                    else:
                        pass
            else:
                if obj_check!='ObjectCollection':
                    new_coll.Add(obj)
                else:
                    pass
        return new_coll
          
    def draw_line_arc(self, sketch, obj_dict, item):
        if type(item)==int:
            obj_key='obj_%s'%str(item)
        elif type(item)==str:
            obj_key=item

        if obj_key in obj_dict.keys():
            if obj_dict[obj_key]['type']=='line_arc':
                pass
            else:
                raise Exception('ERROR: Invalid line arc object for obj ID')
        else:
            raise Exception('ERROR: Obj ID not valid for structure')

        obj=obj_dict[obj_key]
        arc=self.arc_line(sketch, center=obj['center_pt'], start_pt=obj['start_pt'], end_pt=obj['end_pt'])
        return arc

    def draw_line(self, sketch, obj_dict, item):
        if type(item)==int:
            obj_key='obj_%s'%str(item)
        elif type(item)==str:
            obj_key=item

        if obj_key in obj_dict.keys():
            if obj_dict[obj_key]['type']=='line':
                pass
            else:
                raise Exception('ERROR: Invalid line arc object for obj ID')
        else:
            raise Exception('ERROR: Obj ID not valid for structure')

        obj=obj_dict[obj_key]
        line=self.sketch_line(sketch, start=obj['start_pt'], end=obj['end_pt'])
        return line


class iAssembly(com_obj):
    """
    Class for handling Autodesk Inventor Assembly documents with two main capabilities:
    1. Creating images from different perspectives (front, back, left, right, top, bottom)  
    2. Creating UC2 cube assemblies in grid patterns with specific positions and orientations
    """
    
    def __init__(self, path='', prefix='', overwrite=False, units='metric'):
        """
        Initialize assembly document.
        
        Args:
            path: Directory path to the assembly file
            prefix: Assembly filename (IAM file)
            overwrite: Whether to overwrite existing files
            units: Unit system ('imperial' or 'metric') - for UC2 grid functionality
        """
        self.overwrite = overwrite
        self.file_path = path
        self.f_name = prefix
        self.units = units  # Store units for UC2 grid functionality
        
        # Setup COM with Inventor
        super(iAssembly, self).__init__()
        
        if overwrite:
            self.overwrite_file(path, prefix)
        
        # Open assembly
        self.open_assembly(prefix, path)
        
        # Initialize UC2 grid settings if units specified
        if units:
            self.set_units(units)
            # Grid spacing defaults (can be overridden) - UC2 standard spacing
            self.grid_spacing = (50.0, 50.0, 55.0)  # X, Y, Z spacing in mm
        
    def open_assembly(self, prefix='', path=''):
        """
        Opens an existing assembly document or creates new one.
        """
        if prefix == '':
            self.invDoc = self.invApp.Documents.Add(constants.kAssemblyDocumentObject, "", True)
        else:
            # Check if input filename exists
            full_path = os.path.join(path, prefix) if path else prefix
            if os.path.isfile(full_path):
                try:
                    # Set application settings to suppress assembly update dialogs
                    try:
                        self.invApp.SilentOperation = True
                        # Also set options to automatically accept assembly updates
                        self.invApp.Options.GeneralOptions.AutoUpdateAssemblyBefore = True
                    except:
                        pass  # Settings may not be available in all versions
                    
                    self.invDoc = self.invApp.Documents.Open(full_path)
                    
                    # Reset silent operation
                    try:
                        self.invApp.SilentOperation = False
                    except:
                        pass
                        
                except Exception as e:
                    raise Exception(f'ERROR: Unable to open assembly file, check filetype and if file exists: {str(e)}')
                if self.invDoc.DocumentType == constants.kAssemblyDocumentObject:
                    pass
                else:
                    raise Exception('ERROR: Document type is not assembly document')
            else:
                self.invDoc = self.invApp.Documents.Add(constants.kAssemblyDocumentObject, "", True)
        
        # Casting Document to AssemblyDocument
        self.invAssemblyDoc = self.mod.AssemblyDocument(self.invDoc)
        self.compdef = self.invAssemblyDoc.ComponentDefinition
        
        # Opened document handle
        self.oDoc = self.invAppCom.ActiveDocument
        
        # For UC2 grid functionality - setup geometry objects if units are set
        if hasattr(self, 'units') and self.units:
            # Create command manager
            self.cmdManager = self.invApp.CommandManager
            
            # Set transient geometry object
            self.tg = self.invApp.TransientGeometry
            self.trans_obj = self.invApp.TransientObjects
        
        # Object view handle - ensure we have a valid view
        self.view = self.invApp.ActiveView
        if not self.view:
            # If no active view, try to get from document
            if hasattr(self.invDoc, 'ActiveView'):
                self.view = self.invDoc.ActiveView
            elif hasattr(self.invDoc, 'Views') and self.invDoc.Views.Count > 0:
                self.view = self.invDoc.Views.Item(1)
        
    def set_view_orientation(self, view_type):
        """
        Set the view orientation to one of the standard six perspectives.
        
        Args:
            view_type: String indicating view type:
                      'front', 'back', 'left', 'right', 'top', 'bottom',
                      'iso' (isometric), 'custom'
        """
        view_constants = {
            'front': constants.kFrontViewOrientation,
            'back': constants.kBackViewOrientation, 
            'left': constants.kLeftViewOrientation,
            'right': constants.kRightViewOrientation,
            'top': constants.kTopViewOrientation,
            'bottom': constants.kBottomViewOrientation,
            'iso': constants.kIsoTopRightViewOrientation
        }
        
        if view_type.lower() in view_constants:
            # For assemblies, we need to use the active document's view
            try:
                # Method 1: Try using the document's active view directly
                if hasattr(self.invDoc, 'ActiveView'):
                    active_view = self.invDoc.ActiveView
                    if hasattr(active_view, 'Camera'):
                        camera = active_view.Camera
                        camera.ViewOrientationType = view_constants[view_type.lower()]
                        camera.Apply()
                        active_view.Fit()
                        return
                
                # Method 2: Use the Application's active view
                if hasattr(self.invApp, 'ActiveView'):
                    active_view = self.invApp.ActiveView
                    if hasattr(active_view, 'Camera'):
                        camera = active_view.Camera
                        camera.ViewOrientationType = view_constants[view_type.lower()]
                        camera.Apply()
                        active_view.Fit()
                        return
                
                # Method 3: Try using the document's views collection
                if hasattr(self.invDoc, 'Views') and self.invDoc.Views.Count > 0:
                    view = self.invDoc.Views.Item(1)
                    if hasattr(view, 'Camera'):
                        camera = view.Camera
                        camera.ViewOrientationType = view_constants[view_type.lower()]
                        camera.Apply()
                        view.Fit()
                        return
                
                # Method 4: Try using the CommandManager to change view
                if hasattr(self.invApp, 'CommandManager'):
                    # Use the standard view commands
                    view_command_map = {
                        'front': 'AppFrontViewCommand',
                        'back': 'AppBackViewCommand',
                        'left': 'AppLeftViewCommand',
                        'right': 'AppRightViewCommand',
                        'top': 'AppTopViewCommand',
                        'bottom': 'AppBottomViewCommand',
                        'iso': 'AppIsometricViewCommand'
                    }
                    
                    command_name = view_command_map.get(view_type.lower())
                    if command_name:
                        try:
                            cmd = self.invApp.CommandManager.ControlDefinitions.Item(command_name)
                            cmd.Execute()
                            return
                        except:
                            pass
                
                raise Exception(f'All methods failed to set view orientation for "{view_type}"')
                
            except Exception as e:
                raise Exception(f'ERROR: Unable to set view orientation for "{view_type}": {str(e)}')
        else:
            raise Exception(f'ERROR: Invalid view type "{view_type}". Valid types: {list(view_constants.keys())}')
    
    def set_visual_style(self, shaded=True, edges=True, hidden_edges=False, realistic=False):
        """
        Set the visual style for rendering.
        Same functionality as iPart class.
        """
        if realistic == False:
            if shaded == True:
                if edges == False:
                    val = 8708
                else:
                    if hidden_edges == True:
                        val = 8707
                    else:
                        val = 8710
            else:
                if edges == True:
                    if hidden_edges == True:
                        val = 8712
                    else:
                        val = 8711
                else:
                    val = 8706
        else:
            val = 8709
        
        # Try to set display mode on the view
        try:
            if self.view and hasattr(self.view, 'DisplayMode'):
                self.view.DisplayMode = val
            elif hasattr(self.invApp, 'ActiveView') and self.invApp.ActiveView:
                self.invApp.ActiveView.DisplayMode = val
            elif hasattr(self.invDoc, 'ActiveView') and self.invDoc.ActiveView:
                self.invDoc.ActiveView.DisplayMode = val
        except Exception as e:
            # If setting display mode fails, continue without error
            # This is not critical for the overall functionality
            pass
    
    # ASSEMBLY IMAGE CREATION FUNCTIONALITY (from main branch)
    
    def export_image(self, filename='assembly_image.png', file_path='', 
                   image_format='png', width=1920, height=1080):
        """
        Export current view as an image file.
        
        Args:
            filename: Name of the image file
            file_path: Directory path for the image
            image_format: Image format (png, jpg, bmp, tif)
            width: Image width in pixels
            height: Image height in pixels
        
        Returns:
            Full path to the created image file
        """
        if file_path == '':
            file_path = self.file_path if self.file_path else os.getcwd()
        
        full_path = os.path.join(file_path, filename)
        
        try:
            # Ensure the output directory exists
            os.makedirs(file_path, exist_ok=True)
            
            # Method 1: Try using the active view directly
            active_view = None
            if hasattr(self.invApp, 'ActiveView') and self.invApp.ActiveView:
                active_view = self.invApp.ActiveView
            elif hasattr(self.invApp, 'ActiveView'):
                active_view = self.invApp.ActiveView
            
            if active_view and hasattr(active_view, 'SaveImage'):
                active_view.SaveImage(full_path, width, height)
                return full_path
            
            # Method 2: Try using document's export capabilities
            if hasattr(self.invDoc, 'SaveAs'):
                # First try BMP format as it's often more reliable
                if image_format.lower() in ['bmp', "png", 'jpg', 'jpeg', 'tif', 'tiff']:
                    bmp_path = full_path#.replace(f'.{image_format}', '.bmp')
                    # Use a simple approach - export as BMP then convert if needed
                    self.invDoc.SaveAs(bmp_path, True)
                    if os.path.exists(bmp_path) and bmp_path != full_path:
                        # If we need a different format, copy the file
                        shutil.copy2(bmp_path, full_path)
                        os.remove(bmp_path)
                    return full_path
            
            # Method 3: Try using application's TranslatorAddIns if available
            if hasattr(self.invApp, 'TranslatorAddIns'):
                format_map = {
                    'png': 'PNG',
                    'jpg': 'JPEG', 
                    'jpeg': 'JPEG',
                    'bmp': 'BMP',
                    'tif': 'TIFF',
                    'tiff': 'TIFF'
                }
                
                export_format = format_map.get(image_format.lower(), 'PNG')
                
                # Create translator for image export
                translator = self.invApp.TranslatorAddIns.ItemByName(f"{export_format} Image Export")
                
                if translator:
                    context = self.invApp.TransientObjects.CreateTranslationContext()
                    context.Type = constants.kFileBrowseIOMechanism
                    
                    # Set image size options if available
                    if translator.HasSaveCopyAsOptions:
                        options = translator.SaveCopyAsOptions
                        if hasattr(options, 'Width'):
                            options.Width = width
                        if hasattr(options, 'Height'):
                            options.Height = height
                    
                    data_medium = self.invApp.TransientObjects.CreateDataMedium()
                    data_medium.FileName = full_path
                    
                    translator.SaveCopyAs(self.invDoc, context, options, data_medium)
                    return full_path
            
            # Method 4: Try using the view's export via screenshot if available
            if hasattr(self.invApp, 'CommandManager'):
                # Try to trigger screen capture command
                try:
                    # This might work for some versions
                    self.invApp.CommandManager.ControlDefinitions.Item('AppScreenCaptureCommand').Execute()
                    # Note: This would open a dialog, so it's not ideal for automation
                except:
                    pass
            
            # Method 5: Fallback - try to use Windows clipboard and save
            # This is a last resort and might not work in all scenarios
            try:
                import win32clipboard
                import win32con
                from PIL import ImageGrab
                
                # Try to copy screen to clipboard then save
                self.invApp.CommandManager.ControlDefinitions.Item('AppCopyCommand').Execute()
                
                # Wait a bit for clipboard to be populated
                import time
                time.sleep(0.5)
                
                # Get image from clipboard
                img = ImageGrab.grabclipboard()
                if img:
                    # Resize if needed
                    if img.size != (width, height):
                        img = img.resize((width, height))
                    
                    # Save in the requested format
                    img.save(full_path, format=image_format.upper())
                    return full_path
                    
            except ImportError:
                pass  # PIL not available
            except:
                pass  # Some other error with clipboard approach
            
            # If all methods fail, create a simple placeholder or raise an error
            raise Exception(f'Unable to export image using any available method')
        
        except Exception as e:
            raise Exception(f'ERROR: Failed to export image: {str(e)}')
        
        return full_path
    
    def create_perspective_images(self, base_filename='', output_path='', 
                                views=['front', 'back', 'left', 'right', 'top', 'bottom'],
                                image_format='png', width=1920, height=1080,
                                realistic=False, wireframe=False):
        """
        Create images from multiple perspectives of the assembly.
        
        Args:
            base_filename: Base name for image files (view name will be appended)
            output_path: Directory path for output images
            views: List of view perspectives to create
            image_format: Image format for export
            width: Image width in pixels
            height: Image height in pixels
            realistic: Whether to use realistic rendering
            wireframe: Whether to use wireframe mode
        
        Returns:
            List of paths to created image files
        """
        if base_filename == '':
            base_filename = self.f_name.split('.')[0] if self.f_name else 'assembly'
        
        if output_path == '':
            output_path = self.file_path if self.file_path else os.getcwd()
        
        exported_files = []
        
        # Set visual style based on parameters
        if wireframe:
            self.set_visual_style(shaded=False, edges=True, realistic=False)
        else:
            self.set_visual_style(shaded=True, edges=True, realistic=realistic)
        
        for view in views:
            try:
                # Set the view orientation
                self.set_view_orientation(view)
                
                # Create filename with view suffix
                view_filename = f"{base_filename}_{view}.{image_format}"
                
                # Export the image
                full_path = self.export_image(
                    filename=view_filename,
                    file_path=output_path,
                    image_format=image_format,
                    width=width,
                    height=height
                )
                
                exported_files.append(full_path)
                print(f"Created image: {full_path}")
                
            except Exception as e:
                print(f"WARNING: Failed to create {view} view image: {str(e)}")
                continue
        
        return exported_files

    # UC2 GRID ASSEMBLY FUNCTIONALITY (from my branch)
    
    def set_units(self, units):
        """Set assembly document units."""
        if units == 'imperial':
            self.invDoc.UnitsOfMeasure.LengthUnits = constants.kInchLengthUnits
            self.invDoc.UnitsOfMeasure.AngleUnits = constants.kDegreeAngleUnits
        elif units == 'metric':
            self.invDoc.UnitsOfMeasure.LengthUnits = constants.kMillimeterLengthUnits
            self.invDoc.UnitsOfMeasure.AngleUnits = constants.kRadianAngleUnits
        else:
            raise Exception('ERROR: Units must be either imperial or metric')
            
    def unit_conv(self, val_in):
        """Convert units based on current unit system."""
        if hasattr(self, 'units'):
            if self.units == 'imperial':
                mult = 1/25.4  # Convert mm to inches
            elif self.units == 'metric':
                mult = 1
            return val_in * mult
        return val_in  # Default no conversion if units not set
    
    def ang_conv(self, val_in):
        """Convert angle units."""
        if hasattr(self, 'units'):
            if self.units == 'imperial':
                mult = np.pi/180  # Convert degrees to radians
            elif self.units == 'metric':
                mult = 1
            return val_in * mult
        return val_in * np.pi/180  # Default degrees to radians
    
    def place_component(self, component_path, position=(0, 0, 0), rotation=(0, 0, 0)):
        """
        Place a component (part or assembly) at specified position with rotation.
        
        Args:
            component_path: Full path to the component file (.ipt or .iam)
            position: (x, y, z) position in current units
            rotation: (rx, ry, rz) rotation angles in degrees
            
        Returns:
            ComponentOccurrence object
        """
        if not os.path.exists(component_path):
            raise Exception(f'ERROR: Component file not found: {component_path}')
        
        # Convert position to current units
        pos_x = self.unit_conv(position[0])
        pos_y = self.unit_conv(position[1])
        pos_z = self.unit_conv(position[2])
        
        # Convert rotation angles
        rot_x = self.ang_conv(rotation[0])
        rot_y = self.ang_conv(rotation[1])
        rot_z = self.ang_conv(rotation[2])
        
        # Create transformation matrix
        transform_matrix = self.tg.CreateMatrix()
        
        # Apply rotations (order: Z, Y, X)
        if rotation[2] != 0:  # Z rotation
            z_axis = self.tg.CreateUnitVector(0, 0, 1)
            transform_matrix.SetToRotation(rot_z, z_axis, self.tg.CreatePoint(0, 0, 0))
        
        if rotation[1] != 0:  # Y rotation
            y_axis = self.tg.CreateUnitVector(0, 1, 0)
            y_rotation = self.tg.CreateMatrix()
            y_rotation.SetToRotation(rot_y, y_axis, self.tg.CreatePoint(0, 0, 0))
            transform_matrix.PreMultiplyBy(y_rotation)
            
        if rotation[0] != 0:  # X rotation
            x_axis = self.tg.CreateUnitVector(1, 0, 0)
            x_rotation = self.tg.CreateMatrix()
            x_rotation.SetToRotation(rot_x, x_axis, self.tg.CreatePoint(0, 0, 0))
            transform_matrix.PreMultiplyBy(x_rotation)
        
        # Apply translation
        translation = self.tg.CreateVector(pos_x, pos_y, pos_z)
        transform_matrix.SetTranslation(translation)
        
        # Place the component (need to access the compdef attribute)
        if hasattr(self, 'compdef'):
            occurrence = self.compdef.Occurrences.Add(component_path, transform_matrix)
        else:
            # Fallback for compatibility
            occurrence = self.invAssemblyDoc.ComponentDefinition.Occurrences.Add(component_path, transform_matrix)
        
        return occurrence
    
    def set_grid_spacing(self, x_spacing=50.0, y_spacing=50.0, z_spacing=55.0):
        """Set the grid spacing for component placement."""
        self.grid_spacing = (x_spacing, y_spacing, z_spacing)
    
    def place_component_at_grid(self, component_path, grid_x=0, grid_y=0, grid_z=0, rotation=(0, 0, 0)):
        """
        Place a component at grid coordinates.
        
        Args:
            component_path: Full path to the component file
            grid_x, grid_y, grid_z: Grid coordinates (integers)
            rotation: (rx, ry, rz) rotation angles in degrees
            
        Returns:
            ComponentOccurrence object
        """
        # Calculate actual position from grid coordinates
        actual_x = grid_x * self.grid_spacing[0]
        actual_y = grid_y * self.grid_spacing[1] 
        actual_z = grid_z * self.grid_spacing[2]
        
        return self.place_component(component_path, (actual_x, actual_y, actual_z), rotation)
    
    def create_uc2_grid_from_table(self, component_table):
        """
        Create UC2 cube assembly from a table of components.
        
        Args:
            component_table: List of dictionaries with keys:
                - 'file': path to component file
                - 'grid_pos': (x, y, z) grid coordinates
                - 'rotation': (rx, ry, rz) rotation angles in degrees (optional)
                - 'name': component name (optional)
                
        Returns:
            List of placed ComponentOccurrence objects
        """
        placed_components = []
        
        for i, component_info in enumerate(component_table):
            # Extract component information
            comp_file = component_info['file']
            grid_pos = component_info['grid_pos']
            rotation = component_info.get('rotation', (0, 0, 0))
            comp_name = component_info.get('name', f'Component_{i+1}')
            
            try:
                # Place the component
                occurrence = self.place_component_at_grid(
                    comp_file, 
                    grid_pos[0], grid_pos[1], grid_pos[2],
                    rotation
                )
                
                # Set component name if provided
                if comp_name:
                    occurrence.Name = comp_name
                    
                placed_components.append(occurrence)
                print(f"Placed {comp_name} at grid {grid_pos} with rotation {rotation}")
                
            except Exception as e:
                print(f"Failed to place {comp_name}: {str(e)}")
                
        return placed_components
    
    def load_from_optikit_layout(self, json_file_path):
        """
        Load UC2 component layout from optikit-layout.json format.
        
        Args:
            json_file_path: Path to the JSON layout file with optikit format
                
        Returns:
            List of placed ComponentOccurrence objects
        """
        try:
            with open(json_file_path, 'r') as f:
                layout_data = json.load(f)
            
            # Extract uc2_components array
            if 'uc2_components' not in layout_data:
                raise ValueError("JSON file must contain 'uc2_components' array")
            
            components = layout_data['uc2_components']
            
            # Convert to format expected by create_uc2_grid_from_table
            component_table = []
            for comp in components:
                component_entry = {
                    'name': comp.get('name', 'Unknown'),
                    'file': comp['file'],
                    'grid_pos': tuple(comp['grid_pos']),  # Convert array to tuple
                    'rotation': tuple(comp['rotation'])   # Convert array to tuple
                }
                component_table.append(component_entry)
            
            print(f"Loaded {len(component_table)} components from {json_file_path}")
            
            # Use existing method to place components
            return self.create_uc2_grid_from_table(component_table)
            
        except FileNotFoundError:
            raise FileNotFoundError(f"Layout file not found: {json_file_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format in {json_file_path}: {str(e)}")
        except KeyError as e:
            raise ValueError(f"Missing required field in JSON: {str(e)}")
        except Exception as e:
            raise Exception(f"Error loading optikit layout: {str(e)}")
    
    def save(self, file_path='', file_name=''):
        """Save the assembly document."""
        if file_path == '' and file_name == '':
            self.invDoc.Save()
        else:
            if file_path != '':
                save_path = os.path.join(file_path, file_name) if file_name else file_path
            else:
                save_path = file_name
            self.invDoc.SaveAs(save_path, False)
    
    def close(self, save=False):
        """
        Close the assembly document.
        
        Args:
            save: Whether to save before closing
        """
        if save:
            if hasattr(self, 'invAssemblyDoc'):
                self.invAssemblyDoc.Close(SkipSave=False)
            elif hasattr(self, 'invAsmDoc'):
                self.invAsmDoc.Close(SkipSave=False)
            else:
                self.invDoc.Close(SkipSave=False)
        else:
            if hasattr(self, 'invAssemblyDoc'):
                self.invAssemblyDoc.Close(SkipSave=True)
            elif hasattr(self, 'invAsmDoc'):
                self.invAsmDoc.Close(SkipSave=True)
            else:
                self.invDoc.Close(SkipSave=True)


def create_assembly_images_batch(assembly_folder, output_folder='', 
                               views=['front', 'back', 'left', 'right', 'top', 'bottom'],
                               image_format='png', width=1920, height=1080,
                               realistic=False, wireframe=False):
    """
    Batch process multiple assembly files to create images from different perspectives.
    
    Args:
        assembly_folder: Path to folder containing assembly files (IAM)
        output_folder: Path to folder for output images (defaults to assembly_folder)
        views: List of view perspectives to create
        image_format: Image format for export
        width: Image width in pixels  
        height: Image height in pixels
        realistic: Whether to use realistic rendering
        wireframe: Whether to use wireframe mode
    
    Returns:
        Dictionary mapping assembly filenames to lists of created image paths
    """
    if output_folder == '':
        output_folder = assembly_folder
    
    # Find all IAM files in the folder
    iam_pattern = os.path.join(assembly_folder, '*.iam')
    assembly_files = glob.glob(iam_pattern)
    
    if not assembly_files:
        print(f"No assembly files (*.iam) found in {assembly_folder}")
        return {}
    
    results = {}
    
    for asm_file in assembly_files:
        try:
            asm_filename = os.path.basename(asm_file)
            base_name = os.path.splitext(asm_filename)[0]
            
            print(f"\nProcessing assembly: {asm_filename}")
            
            # Open the assembly
            assembly = iAssembly(path=assembly_folder, prefix=asm_filename, overwrite=False)
            
            # Create output subfolder for this assembly
            asm_output_folder = output_folder #os.path.join(output_folder, base_name + '_images')
            
            # Create perspective images
            exported_files = assembly.create_perspective_images(
                base_filename=base_name,
                output_path=asm_output_folder,
                views=views,
                image_format=image_format,
                width=width,
                height=height,
                realistic=realistic,
                wireframe=wireframe
            )
            
            results[asm_filename] = exported_files
            
            # Close the assembly
            assembly.close(save=False)
            
            print(f"Completed processing {asm_filename}: {len(exported_files)} images created")
            
        except Exception as e:
            print(f"ERROR processing {asm_file}: {str(e)}")
            results[asm_filename] = []
            continue
    
    return results


class structure(object):
    def __init__(self, part, sketch, start=(0.0,0.0), direction=0):
        
        part_type=self.obj_type_check(part)
        sketch_type=self.obj_type_check(sketch)
        
        if sketch_type!='sketch':
            raise Exception('ERROR: Invalid sketch type=%s. Input sketch of wrong type, must be sketch type'%(sketch_type))
        else:
            pass
        
        if part_type!='iPart':
            raise Exception('ERROR: Invalid part type=%s. Input part of wrong type, must be iPart type'%(sketch_type))
        else:
            pass
        
        self.start=start
        self.last=start
        self.last_dir=direction
        self.sketch=sketch
        self.part=part
        self.obj_dict={'start':{'type':'origin', 'pts':[start]}}
        self.obj_num=0
        
    def obj_type_check(self, obj):
        return str(type(obj)).split(' ')[-1].split('.')[-1].split('\'')[0]
        
    def move(self, distance, direction=None):
        if direction == None: direction = self.last_dir
        self.last = translate_pt(self.last, ang2pt(direction, distance))
    
    def append_element(self, obj_handle):
        self.obj_num+=1
        self.obj_dict['obj_%s'%str(self.obj_num)]=obj_handle
    
    def get_pts(self):
        pts=[self.obj_dict['start']['pts'][0]]
        obj_keys=[]
        for key in iter(self.obj_dict.keys()):
            if "point" in self.obj_dict[key]['type']:
                pts+=self.obj_dict[key]['pts']
                obj_keys.append(key)
        pts=remove_duplicate_pts(pts)
        return [pts, obj_keys]
        
    def get_line_pts(self):
        pts=[]
        obj_keys=[]
        for key in iter(self.obj_dict.keys()):
            if "line" in self.obj_dict[key]['type']:
                if "point" in self.obj_dict[key]['type']:
                    pass
                else:
                    for sub_key in iter(self.obj_dict[key]):
                        if "_pt" in sub_key:
                            pts.append(self.obj_dict[key][sub_key])
                    obj_keys.append(key)
        pts.append(pts[0])
        return [pts, obj_keys]  
    
    def get_poly_pts(self):
        pts=[]
        obj_keys=[]
        for key in iter(self.obj_dict.keys()):
            if "poly" in self.obj_dict[key]['type']:
                pts+=self.obj_dict[key]['pts']
                obj_keys.append(key)
        return [pts, obj_keys]
    
    def draw_poly(self, item=1):
        sketch=self.sketch
        obj_dict=self.obj_dict
        if type(item)==int:
            obj_key='obj_%s'%str(item)
        elif type(item)==str:
            obj_key=item
            
        try:
            if 'poly' in obj_dict[obj_key]['type']:
                pass
            else:
                raise Exception('ERROR: Invalid structure type, must be polygon')
        except:
            raise Exception('ERROR: Poly object does not exist, check item number')
        
        pts=obj_dict[obj_key]['pts']
        
        self.poly_line_coll=self.part.poly_lines(sketch, pts)
        return self.poly_line_coll


    def draw_path(self, item='all', close_path=False):
        sketch=self.sketch
        obj_dict=self.obj_dict
        if len(list(obj_dict.keys()))<2:
            raise Exception('ERROR: Object list is empty')
        else: 
            pass
        if type(item)==int:
            obj_keys=['obj_%s'%str(item)]
        elif type(item)==str:
            if item=='all':
                obj_keys=[]
                for key in iter(obj_dict.keys()):
                    if key=='start':
                        pass
                    else:
                        obj_keys.append(key)
            elif item.split('_')[0]=='obj':
                obj_keys=[item]
            else:
                raise Exception('ERROR: Invalid object key, must be all, or object identifier string')
        elif type(item)==list:
            if type(item[0])==str:
                obj_keys=[]
                for keys in item:
                    if keys in obj_dict.keys():
                        obj_keys.append()
                    else:
                        raise Exception('ERROR: Invalid structure key')
            else:
                raise Exception('ERROR: Invalid structure key identifier, must be of form obj_(int value)')
        else:
            raise Exception('ERROR: Invalid object identifer input, must be all, string of obj ID, or list of obj ID')
        
        if obj_keys[0]!='line':
            start_pt=obj_dict['start']['pts'][0]
        else:
            start_pt=obj_dict[obj_keys[0]]['start_pt']
        
        lines=[]
        
        final_pt=obj_dict[obj_keys[-1]]['end_pt']
        
        first_pt=start_pt
        
        for key in obj_keys:
            s_copy=copy.deepcopy(obj_dict)
            s_copy[key]['start_pt']=start_pt
            if obj_dict[key]['type']=='line_arc':
                lines.append(self.draw_line_arc(s_copy, key))
            elif obj_dict[key]['type']=='line':
                lines.append(self.draw_line(s_copy, key))
            elif obj_dict[key]['type']=='spline':
                lines.append(self.draw_spline(s_copy, key))
                if len(lines)>1:
                    lines[-1].StartSketchPoint.Merge(lines[-2].EndSketchPoint)
                
            end_pt_coord=round_pt(self.part.inv_unit_conv((lines[-1].EndSketchPoint.Geometry.X, lines[-1].EndSketchPoint.Geometry.Y)))

            if type(start_pt)==tuple:
                start_pt_check=round_pt(start_pt)
            else:
                start_pt_check=round_pt(self.part.inv_unit_conv((start_pt.Geometry.X, start_pt.Geometry.Y)))

            if end_pt_coord==start_pt_check:
                start_pt=lines[-1].StartSketchPoint
            else:
                start_pt=lines[-1].EndSketchPoint
        
        if close_path==True and first_pt!=final_pt:
            line_obj=sketch.sketch_obj.SketchLines
            lines.append(line_obj.AddByTwoPoints(start_pt, lines[0].StartSketchPoint))
        elif close_path==True and first_pt==final_pt:
            start_pt.Merge(lines[0].StartSketchPoint)
        else:
            pass
        
        obj_coll=self.part.new_obj_collection()
        for vals in lines:
            obj_coll.Add(vals)
        
        return obj_coll

    def get_plt_pts(self, item='all', close_path=False, curve_res=10):
        obj_dict=self.obj_dict
        if len(list(obj_dict.keys()))<2:
            raise Exception('ERROR: Object list is empty')
        else: 
            pass
        if type(item)==int:
            obj_keys=['obj_%s'%str(item)]
        elif type(item)==str:
            if item=='all':
                obj_keys=[]
                for key in iter(obj_dict.keys()):
                    if key=='start':
                        pass
                    else:
                        obj_keys.append(key)
            elif item.split('_')[0]=='obj':
                obj_keys=[item]
            else:
                raise Exception('ERROR: Invalid object key, must be all, or object identifier string')
        elif type(item)==list:
            if type(item[0])==str:
                obj_keys=[]
                for keys in item:
                    if keys in obj_dict.keys():
                        obj_keys.append()
                    else:
                        raise Exception('ERROR: Invalid structure key')
            else:
                raise Exception('ERROR: Invalid structure key identifier, must be of form obj_(int value)')
        else:
            raise Exception('ERROR: Invalid object identifer input, must be all, string of obj ID, or list of obj ID')
        
        if obj_keys[0]!='line':
            start_pt=obj_dict['start']['pts'][0]
        else:
            start_pt=obj_dict[obj_keys[0]]['start_pt']
        
        pts=[]

        for key in obj_keys:
            s_copy=copy.deepcopy(obj_dict)
            s_copy[key]['start_pt']=start_pt
            if obj_dict[key]['type']=='line_arc':
                start=obj_dict[key]['start_pt']
                end=obj_dict[key]['end_pt']
                center=obj_dict[key]['center_pt']
                arc_pts=arc_pts_pattern(start, end, center, curve_res)
                for pt in arc_pts:
                    pts.append(pt)
            elif obj_dict[key]['type']=='line':
                line_pts=[obj_dict[key]['start_pt'], obj_dict[key]['end_pt']]
                for pt in line_pts:
                    pts.append(pt)
            elif obj_dict[key]['type']=='spline':
                for pt in obj_dict[key]['pts']:
                    pts.append(pt)
        return pts
            
                
    def draw_line_arc(self,  obj_dict, item):
        sketch=self.sketch

        if type(item)==int:
            obj_key='obj_%s'%str(item)
        elif type(item)==str:
            obj_key=item

        if obj_key in obj_dict.keys():
            if obj_dict[obj_key]['type']=='line_arc':
                pass
            else:
                raise Exception('ERROR: Invalid line arc object for obj ID')
        else:
            raise Exception('ERROR: Obj ID not valid for structure')

        obj=obj_dict[obj_key]
        arc=self.part.arc_line(sketch, center=obj['center_pt'], start_pt=obj['start_pt'], end_pt=obj['end_pt'], flip=obj['flip'])
        return arc

    def draw_line(self, obj_dict, item):
        sketch=self.sketch
        if type(item)==int:
            obj_key='obj_%s'%str(item)
        elif type(item)==str:
            obj_key=item

        if obj_key in obj_dict.keys():
            if obj_dict[obj_key]['type']=='line':
                pass
            else:
                raise Exception('ERROR: Invalid line arc object for obj ID')
        else:
            raise Exception('ERROR: Obj ID not valid for structure')

        obj=obj_dict[obj_key]
        line=self.part.sketch_line(sketch, start=obj['start_pt'], end=obj['end_pt'])
        return line

    def draw_spline(self, obj_dict, item):
        sketch=self.sketch
        if type(item)==int:
            obj_key='obj_%s'%str(item)
        elif type(item)==str:
            obj_key=item

        if obj_key in obj_dict.keys():
            if obj_dict[obj_key]['type']=='spline':
                pass
            else:
                raise Exception('ERROR: Invalid line arc object for obj ID')
        else:
            raise Exception('ERROR: Obj ID not valid for structure')

        obj=obj_dict[obj_key]
        spline=self.part.sketch_spline(sketch, obj['pts'])
        return spline

    def add_bspline(self, num_pts, control_pts, degree=3, flip_dir=False, rotation=None, mirror=False, mirror_angle=0):
        points=b_spline(control_pts, num=num_pts, degree=degree)
        if flip_dir==True:
            points=points[::-1]
        if rotation!=None:
            points=rotate_pts(points, angle=rotation, center=points[0])
        if mirror==True:
            points=mirror_pts(points, axis_angle=mirror_angle, axis_pt=points[0])
        dx=self.last[0]-points[0][0]
        dy=self.last[1]-points[0][1]
        new_pts=translate_pts(points, (dx, dy))
        spline_obj={'type':'spline','pts':new_pts, 'start_pt':new_pts[0], 'end_pt':new_pts[-1]}
        self.last=new_pts[-1]
        self.append_element(spline_obj)
        self.structure_key=list(self.obj_dict.keys())[-1]

    def add_point_arc(self, start_angle=0, stop_angle=180, radius=1, segments=9, flip_dir=False, mirror=False, rotation=0):
        start=round_pt(self.last)
        init_angle=0
        sweep_angle=stop_angle-start_angle
        if sweep_angle<0:
            sweep_dir=1
        else:
            sweep_dir=-1
        if flip_dir==False:
            flip=1.0
        else:
            flip=-1.0
        center_dir=self.last_dir+sweep_dir*flip*90+rotation
        center_pt=round_pt(translate_pt(start, ang2pt(center_dir, radius)))
        start_angle=init_angle+start_angle+rotation
        stop_angle=init_angle+stop_angle+rotation
        pts=arc_pattern(start_angle, stop_angle, radius, center_pt, segments)
        if mirror==False:
            pass
        else:
            pts=mirror_pts(pts, rotation-90, center_pt)
        pts=round_pts(pts)
        self.last=pts[-1]
        self.last_dir=stop_angle
        point_obj={'type':'point_arc', 'pts':round_pts(pts)}
        self.append_element(point_obj)
        self.structure_key=list(self.obj_dict.keys())[-1]
        self.pts=round_pts(pts)
    
    def add_line(self, distance, direction):
        self.pts=[round_pt(self.last)]
        end_pt=round_pt(translate_pt(self.pts[-1], ang2pt(direction, distance)))
        self.pts.append(end_pt)
        self.last=end_pt
        self.last_dir=direction
        line_obj={'type':'line', 'start_pt':self.pts[0], 'end_pt':self.pts[1]}
        self.append_element(line_obj)
        self.structure_key=list(self.obj_dict.keys())[-1]
        
    def add_point_line(self, distance, direction, num_points):
        start=self.last
        disp=float(distance)/(num_points-1)
        pts=[start]
        for i in range(num_points-1):
            pts.append(round_pt(translate_pt(pts[-1], ang2pt(direction, disp))))
        self.last=pts[-1]
        self.last_dir=direction
        point_obj={'type':'point_line', 'pts':pts }
        self.append_element(point_obj)
        self.structure_key=list(self.obj_dict.keys())[-1]
        self.pts=pts
    
    def add_line_arc(self, start_angle=0, stop_angle=180, radius=1, flip_dir=False, mirror=False, rotation=0):
        start=round_pt(self.last)
        center_dir=self.last_dir+rotation+90
        center_pt=round_pt(translate_pt(start, ang2pt(center_dir, radius)))
        start_angle=start_angle+rotation
        stop_angle=stop_angle+rotation
        sweep_angle=stop_angle-start_angle
        pts=arc_pattern(start_angle, stop_angle, radius, center_pt, segments=2)
        if mirror==False:
            pass
        else:
            pts=mirror_pts(pts, rotation-90, center_pt)
        pts=round_pts(pts)
        self.last=pts[-1]
        self.last_dir=stop_angle
        line_obj={'type':'line_arc', 'center_pt':center_pt, 'start_pt': start, 'end_pt':self.last, 'flip':flip_dir}
        self.append_element(line_obj)
        self.structure_key=list(self.obj_dict.keys())[-1]
        
    def add_point(self, offset, ref_pt=None):
        if ref_pt==None:
            ref_pt=round_pt(self.last)
        else:
            if type(ref_pt)==tuple:
                if len(ref_pt)==2:
                    pass
                else:
                    raise Exception("ERROR: Ref point muts be tuple of len=2")
            else:
                raise Exception("ERROR: Ref point must be tuple of len=2")
        end_pt=round_pt(translate_pt(ref_pt, offset))
        self.last=end_pt
        point_obj={'type':'point', 'pts':[end_pt]}
        self.append_element(point_obj)
        self.structure_key=list(self.obj_dict.keys())[-1]
        self.pts=round_pt(end_pt)
        


def get_next_filename(datapath,prefix,suffix=''):
    ii = next_file_index(datapath, prefix)
    return "%05d_" % (ii) + prefix +suffix

def next_file_index(datapath,prefix=''):
    """Searches directories for files of the form *_prefix* and returns next number
        in the series"""

    dirlist=glob.glob(os.path.join(datapath,'*_'+prefix+'*'))
    dirlist.sort()
    try:
        ii=int(os.path.split(dirlist[-1])[-1].split('_')[0])+1
    except:
        ii=0
    return ii
        
def round_pt(pt, digits=5):
    return (round(pt[0], digits), round(pt[1], digits))

def round_pts(pts, digits=5):
    return [(round(pt[0], digits), round(pt[1], digits)) for pt in pts]

        
def remove_duplicate_pts(seq):
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]

def distance(tuple1, tuple2):
    dx = tuple1[0] - tuple2[0]
    dy = tuple1[1] - tuple2[1]
    return sqrt(dx ** 2 + dy ** 2)


def ang2pt(direction, distance):
    theta = np.pi * direction / 180
    dx = distance * cos(theta)
    dy = distance * sin(theta)
    return (dx, dy)


def vec_rot(vector, angle):
    rot_matrix=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    return np.dot(rot_matrix, vector)

def arc_pts_pattern(start, end, center, num_pts, return_list=True, dir=None):
    P_1=center
    P_2=start
    P_3=end
    D_12=distance(P_1, P_2)
    D_13=distance(P_1, P_3)
    D_23=distance(P_2, P_3)
    ang=np.arccos((D_12**2+D_13**2-D_23**2)/(2*D_12*D_13))
    ang_trans=ang/(num_pts-1)
    start_dir=np.array([(P_2[0]-P_1[0])/D_12, (P_2[1]-P_1[1])/D_12])
    end_dir=np.array([(P_3[0]-P_1[0])/D_13, (P_3[1]-P_1[1])/D_13])
    dir_check=np.sign(np.cross(start_dir, end_dir))
    if dir_check==0 and type(dir)!=type(None):
        dir=dir
    elif dir_check==0 and type(dir)==type(None):
        dir=1
    else:
        dir=dir_check
    pts=[]
    new_ang=0
    for i in range(num_pts):
        new_vec=D_12*vec_rot(start_dir, dir*new_ang)
        pts.append((center[0]+new_vec[0], center[1]+new_vec[1]))
        new_ang+=ang_trans
    if return_list==False:
        return np.transpose(np.array(pts))
    else:
        return pts
def mirror_x(pts, xline, concatenate=True):
    if concatenate==True:
        pts_x=np.concatenate((pts[0], xline-pts[0][::-1]))
        pts_y=np.concatenate((pts[1], pts[1][::-1]))
        return np.array([pts_x, pts_y])
    else:
        return np.array([xline-pts[0], pts[1]])

def rotate_pt(p, angle, center=(0, 0)):
    """rotates point p=(x,y) about point center (defaults to (0,0)) by CCW angle (in degrees)"""
    dx = p[0] - center[0]
    dy = p[1] - center[1]
    theta = np.pi * angle / 180.
    return (center[0] + dx * cos(theta) - dy * sin(theta), center[1] + dx * sin(theta) + dy * cos(theta))


def rotate_pts(points, angle, center=(0, 0)):
    """Rotates an array of points one by one using rotate_pt"""
    return [rotate_pt(p, angle, center) for p in points]


def translate_pt(p, offset):
    """Translates point p=(x,y) by offset=(x,y)"""
    return (p[0] + offset[0], p[1] + offset[1])


def translate_pts(points, offset):
    """Translates an array of points one by one using translate_pt"""
    return [translate_pt(p, offset) for p in points]


def orient_pt(p, angle, offset):
    """Orient_pt rotates point p=(x,y) by angle (in degrees) and then translates it to offset=(x,y)"""
    return translate_pt(rotate_pt(p, angle), offset)


def orient_pts(points, angle, offset):
    """Orients an array of points one by one using orient_pt"""
    return [orient_pt(p, angle, offset) for p in points]


def scale_pt(p, scale):
    """Scales p=(x,y) by scale"""
    return (p[0] * scale[0], p[1] * scale[1])


def scale_pts(points, scale):
    """Scales an array of points one by one using scale_pt"""
    return [scale_pt(p, scale) for p in points]


def mirror_pt(p, axis_angle, axis_pt):
    """Mirrors point p about a line at angle "axis_angle" intercepting point "axis_pt" """
    theta = axis_angle * np.pi / 180.
    return (axis_pt[0] + (-axis_pt[0] + p[0]) * cos(2 * theta) + (-axis_pt[1] + p[1]) * sin(2 * theta),
            p[1] + 2 * (axis_pt[1] - p[1]) * cos(theta) ** 2 + (-axis_pt[0] + p[0]) * sin(2 * theta) )


def mirror_pts(points, axis_angle, axis_pt):
    """Mirrors an array of points one by one using mirror_pt"""
    return [mirror_pt(p, axis_angle, axis_pt) for p in points]

def arc_pattern(start_angle, stop_angle, radius, center_pt=(2,1), segments=9):
    if type(center_pt)==tuple or type(center_pt)==list:
        if len(center_pt)==2:
            pass
        else:
            raise Exception('ERROR: Center_pt must be list of len=2 of form [x,y]')
    else:
        raise Exception('ERROR: Invalid type, centerpoint must be list len=2 of form [x,y]')
    pts = []
    x_0=center_pt[0]
    y_0=center_pt[1]
    for ii in range(segments):
        theta = (start_angle + ii / (segments - 1.) * (stop_angle - start_angle)) * pi / 180.
        p = (x_0+radius * cos(theta), y_0+radius * sin(theta))
        pts.append(p)
    return pts


def circle_pattern(radius, center_pt=(0,0), segments=3, offset=0):
    if type(center_pt)==tuple or type(center_pt)==list:
        if len(center_pt)==2:
            pass
        else:
            raise Exception('ERROR: Center_pt must be list of len=2 of form [x,y]')
    else:
        raise Exception('ERROR: Invalid type, centerpoint must be list len=2 of form [x,y]')
    pts = []
    x_0=center_pt[0]
    y_0=center_pt[1]
    rot_ang=360/segments
    theta=offset*np.pi/180
    for ii in range(segments):
        p = (x_0+radius * cos(theta), y_0+radius * sin(theta))
        theta += rot_ang * pi / 180.
        pts.append(p)
    return pts

def bernstein_poly(order, k):
    """
    Bernstein polynomial.

    """
    coeff = binom(order, k)
    def _bpoly(x):
        return coeff * x ** k * (1 - x) ** (order - k)

    return _bpoly


def b_spline(c_points, num=200, degree=3):
    """
    Build Bézier curve from control points.

    """
    N = len(c_points)
    # Prevent degree from exceeding count-1, otherwise splev will crash
    degree = np.clip(degree,1,N-1)

    t = np.linspace(0, 1, num=num)
    curve = np.zeros((num, 2))
    for ii in range(N):
        curve += np.outer(bernstein_poly(degree , ii)(t), c_points[ii])
    return [tuple(pt) for pt in curve]
