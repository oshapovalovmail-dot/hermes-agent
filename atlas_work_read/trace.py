"""Read only an explicitly selected existing native trace tab, in background.

No target creation/navigation/activation, foreground, cookies/storage/headers,
custom expressions, browser startup or model-selected native target identity.
"""
from atlas_bridge.contract import Denied

class SelectedTraceReader:
    def __init__(self,driver,selection,bundle):
        self.driver=driver;self.selection=selection;self.bundle=bundle
    def read(self,scope,url,max_chars=12000):
        s=self.bundle.module;self.bundle.verify();s.validate_trace(url);s.valid_bound(max_chars)
        target=self.selection(scope,url)
        if type(target)is not str or not target:raise Denied('explicit_native_tab_selection_required')
        def check():
            info=self.driver('Target.getTargetInfo',{'targetId':target}).get('targetInfo',{})
            if info.get('targetId')!=target or info.get('type')!='page' or info.get('url')!=url or self.selection(scope,url)!=target:raise Denied('selected_native_tab_changed')
        check();session=None
        try:
            session=self.driver('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
            # Exact integrity-admitted published fixed DOM expression only.
            value=self.driver('Runtime.evaluate',{'expression':s.TRACE_SCRIPT,'returnByValue':True,'timeout':2000},session).get('result',{}).get('value',{})
            check()
            if type(value)is not dict or value.get('url')!=url:raise Denied('selected_trace_redirect_denied')
            if value.get('ready') is not True or type(value.get('text'))is not str:return s.result(False,'trace_not_ready')
            return s.result(True,'ok',source=url,text=value['text'],max_chars=max_chars)
        finally:
            if session is not None:self.driver('Target.detachFromTarget',{'sessionId':session})
