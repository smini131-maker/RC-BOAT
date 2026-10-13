# QGIS 3 Python Console: import runpy; runpy.run_path(r'C:/.../qgis/setup_qgis_layers.py')
from pathlib import Path
from qgis.core import (QgsProject, QgsVectorLayer, QgsMarkerSymbol,
                       QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor, QFont
folder=Path(__file__).resolve().parent
layers=[
    ('actual_track.csv','Actual trajectory','0,165,82,255','TimeStep'),
    ('target_left.csv','LEFT target route','25,95,235,255','Index'),
    ('target_center.csv','CENTER target route','125,125,125,255','Index'),
    ('target_right.csv','RIGHT target route','215,35,45,255','Index'),
]
project=QgsProject.instance()
loaded=[]
for filename,name,color,label in layers:
    csv=folder/filename
    if not csv.is_file():
        print('Missing layer:',csv)
        continue
    uri=csv.as_uri()+'?type=csv&detectTypes=yes&xField=Longitude&yField=Latitude&crs=EPSG:4326'
    layer=QgsVectorLayer(uri,name,'delimitedtext')
    if not layer.isValid():
        print('Invalid layer:',filename,uri)
        continue
    symbol=QgsMarkerSymbol.createSimple({'name':'circle','color':color,
           'outline_color':'30,30,30,255','outline_width':'0.15',
           'size':'1.9' if filename=='actual_track.csv' else '2.3'})
    layer.renderer().setSymbol(symbol)
    fmt=QgsTextFormat();fmt.setFont(QFont('Arial',8));fmt.setSize(8);fmt.setColor(QColor('#222222'))
    options=QgsPalLayerSettings()
    options.fieldName='format_number(to_real("TimeStep"), 2)' if label=='TimeStep' else 'to_string("Index")'
    options.isExpression=True
    options.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(options))
    layer.setLabelsEnabled(True)
    project.addMapLayer(layer);loaded.append(layer)
if not loaded: raise RuntimeError('No valid CSV layers loaded; check coordinate columns')
project.setCrs(loaded[0].crs())
canvas=iface.mapCanvas()
canvas.setExtent(loaded[0].extent());canvas.refresh()
result=folder/'experiment_layers.qgz'
if not project.write(str(result)): raise RuntimeError('QGIS project save failed: '+str(result))
print('Loaded',len(loaded),'layers; project saved to',result)
print('Optional basemap: TMS for Korea / TMS4 Korea -> VWorld Satellite')
