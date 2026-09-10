#!/usr/bin/env python3
"""Illustrative classic skin render using test data, not an Enigma2 screenshot."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from test_e2doctor import p,Session
screen=p.E2DoctorDashboard(Session())
screen['change'].setText('Podgląd układu • przykładowe dane')
root=ET.fromstring(screen.skin);size=tuple(map(int,root.attrib['size'].split(',')))
img=Image.new('RGB',size,root.attrib['backgroundColor'])
fontpath='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def text(layer,value,font,color,center=False):
    draw=ImageDraw.Draw(layer);f=ImageFont.truetype(fontpath,font)
    value=str(value).split('\n')[0]
    x=max(0,(layer.width-draw.textlength(value,font=f))/2) if center else 0
    draw.text((x,0),value,font=f,fill=color)
def col(n):return '#%06x'%(n&0xffffff)
fonts={0:14,1:24,2:p.E2D_FONT_SMALL,3:p.E2D_FONT_TINY,4:15}
for node in root:
    a=node.attrib;x,y=map(int,a['position'].split(','));w,h=map(int,a['size'].split(','));name=a.get('name') or a.get('source')
    layer=img.crop((x,y,x+w,y+h))
    if a.get('backgroundColor'):layer=Image.new('RGB',(w,h),a['backgroundColor'])
    if name=='logo':
        icon=Image.open(a['pixmap']).convert('RGBA').resize((w,h));layer.paste(icon,(0,0),icon)
    elif name=='dashboard':
        for i,row in enumerate(screen['dashboard'].list[:4]):
            yy=i*72
            if yy>=h:break
            cell=Image.new('RGB',(w,72),'#08131A')
            for entry in screen['dashboard'].build_entry(*row)[1:]:
                ex,ey=entry['pos'];ew,eh=entry['size'];part=cell.crop((ex,ey,ex+ew,ey+eh))
                bg=entry.get('backcolor_sel' if i==0 else 'backcolor')
                if bg is not None:part=Image.new('RGB',(ew,eh),col(bg))
                if entry.get('text') and entry['text']!=row[1]:text(part,entry['text'],fonts[entry['font']],col(entry.get('color',0xffffff)))
                cell.paste(part,(ex,ey))
            icon=Image.open(p.PLUGIN_PATH+'/icons/hd/'+row[0]+'.png').convert('RGBA') if (Path(p.PLUGIN_PATH)/'icons/hd'/(row[0]+'.png')).exists() else None
            if icon:
                icon=icon.resize((42,42));cell.paste(icon,(30,11),icon)
            layer.paste(cell,(0,yy))
    elif name=='score_bar':
        ImageDraw.Draw(layer).rectangle((0,0,w-1,h-1),outline='#2AD0D9')
    elif 'font' in a:
        text(layer,screen[name].getText(),int(a['font'].split(';')[1]),a.get('foregroundColor','#FFFFFF'),a.get('halign')=='center')
    img.paste(layer,(x,y))
target=Path(sys.argv[1]);img.save(target);screen.close()
