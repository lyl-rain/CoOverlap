"""Raster preview of these rect/text-only scientific SVGs; no image edits."""
import sys,xml.etree.ElementTree as E
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
p=Path(sys.argv[1]);t=E.fromstring(p.read_text());W,H=int(t.get('width')),int(t.get('height'))
im=Image.new('RGB',(W,H),'white');d=ImageDraw.Draw(im)
for e in t:
    tag=e.tag.rsplit('}',1)[-1]
    if tag=='rect':
        x,y=float(e.get('x',0)),float(e.get('y',0));w,h=e.get('width'),e.get('height')
        w=W if w=='100%' else float(w);h=H if h=='100%' else float(h)
        d.rectangle((x,y,x+w,y+h),fill=e.get('fill','black'))
    elif tag=='text':
        font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',int(e.get('font-size',16)))
        d.text((float(e.get('x')),float(e.get('y'))),e.text or '',font=font,fill='black',anchor='ls')
    else:raise ValueError('unsupported SVG element: '+tag)
im.save(p.with_suffix('.png'))
