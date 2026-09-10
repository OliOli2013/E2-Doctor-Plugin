"""Minimal API model, not an emulator or proof of receiver compatibility."""
import sys
import types

class Component:
    def __init__(self,*args,**kwargs):
        self.text=args[0] if args else ''
        self.onSelectionChanged=[]
        self.list=[]
        self.index=0
        self.l=self
    def setText(self,x): self.text=x
    def getText(self): return self.text
    def setValue(self,x): self.value=x
    def setList(self,x): self.list=x; self.index=0
    def getCurrent(self): return self.list[self.index] if self.list else None
    def getSelectedIndex(self): return self.index
    def getSelectionIndex(self): return self.index
    def setItemHeight(self,x): self.item_height=x
    def setFont(self,*args): pass
    def setBuildFunc(self,x): self.builder=x
    def pageUp(self): pass
    def pageDown(self): pass
    def up(self):
        if self.list:self.index=(self.index-1)%len(self.list)
        for fn in self.onSelectionChanged:fn()
    def down(self):
        if self.list:self.index=(self.index+1)%len(self.list)
        for fn in self.onSelectionChanged:fn()
    def moveToIndex(self,x):self.index=x

class Screen(dict):
    def __init__(self,session,*args):
        dict.__init__(self);self.session=session;self.onClose=[];self.onShown=[];self.onLayoutFinish=[]
    def setTitle(self,x):pass
    def close(self,*args):
        self.closed=args
        for fn in self.onClose:fn()

class MessageBox(Screen):
    TYPE_INFO=0;TYPE_ERROR=1;TYPE_YESNO=2;TYPE_WARNING=3
class Descriptor:
    WHERE_PLUGINMENU=1;WHERE_EXTENSIONSMENU=2;WHERE_SESSIONSTART=3
    def __init__(self,**kwargs):self.__dict__.update(kwargs)
class Timer:
    def __init__(self):self.callback=[];self.running=False
    def start(self,*args):self.running=True
    def startLongTimer(self,*args):self.running=True
    def stop(self):self.running=False

class Session:
    def __init__(self):self.opened=[]
    def open(self,*args,**kwargs):self.opened.append((args,kwargs))
    def openWithCallback(self,*args,**kwargs):self.opened.append((args,kwargs))


def install(width=1280,height=720):
    defs={
      'Plugins.Plugin':{'PluginDescriptor':Descriptor},
      'Screens.Screen':{'Screen':Screen},'Screens.MessageBox':{'MessageBox':MessageBox},
      'Components.ActionMap':{'ActionMap':Component},'Components.Label':{'Label':Component},
      'Components.MenuList':{'MenuList':Component},'Components.ScrollLabel':{'ScrollLabel':Component},
      'Components.Sources.StaticText':{'StaticText':Component},'Components.Pixmap':{'Pixmap':Component},
      'Components.ProgressBar':{'ProgressBar':Component},
      'Components.MultiContent':{'MultiContentEntryText':lambda **kw:kw,'MultiContentEntryPixmapAlphaBlend':lambda **kw:kw},
      'Tools.LoadPixmap':{'LoadPixmap':lambda *args,**kwargs:None},
      'Components.Language':{'language':types.SimpleNamespace(getLanguage=lambda:'pl_PL')},
      'enigma':{'eListboxPythonMultiContent':object,'gFont':lambda *args:args,'eTimer':Timer,
                'getDesktop':lambda _:types.SimpleNamespace(size=lambda:types.SimpleNamespace(width=lambda:width,height=lambda:height)),
                'RT_HALIGN_LEFT':0,'RT_VALIGN_CENTER':1,'RT_HALIGN_CENTER':2,'RT_HALIGN_RIGHT':4,'RT_VALIGN_TOP':8}
    }
    for name,values in defs.items():
        bits=name.split('.')
        for n in range(1,len(bits)+1):
            key='.'.join(bits[:n])
            if key not in sys.modules:
                mod=types.ModuleType(key);mod.__path__=[];sys.modules[key]=mod
        sys.modules[name].__dict__.update(values)
