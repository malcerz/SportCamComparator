"""Windows PDH GPU engine samples for the native exporter PID (diagnostics only)."""
import ctypes as c
from ctypes import wintypes as w


class ValueUnion(c.Union):
    _fields_ = [('doubleValue', c.c_double), ('longValue', w.LONG), ('largeValue', c.c_longlong)]


class Value(c.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('status', w.DWORD), ('value', ValueUnion)]


class Item(c.Structure):
    _fields_ = [('name', w.LPWSTR), ('value', Value)]


class GpuCounter:
    def __init__(self):
        self.api = c.WinDLL('pdh')
        self.query = w.HANDLE()
        self.counter = w.HANDLE()
        self.api.PdhOpenQueryW.argtypes = [w.LPCWSTR, c.c_size_t, c.POINTER(w.HANDLE)]
        self.api.PdhAddEnglishCounterW.argtypes = [w.HANDLE, w.LPCWSTR, c.c_size_t, c.POINTER(w.HANDLE)]
        self.api.PdhCollectQueryData.argtypes = [w.HANDLE]
        self.api.PdhGetFormattedCounterArrayW.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.c_void_p]
        self.api.PdhCloseQuery.argtypes = [w.HANDLE]
        self.available = self.api.PdhOpenQueryW(None, 0, c.byref(self.query)) == 0
        if self.available:
            self.available = self.api.PdhAddEnglishCounterW(self.query,
                r'\GPU Engine(*)\Utilization Percentage', 0, c.byref(self.counter)) == 0
        if self.available:
            self.api.PdhCollectQueryData(self.query)

    def sample(self, pid):
        if not self.available or self.api.PdhCollectQueryData(self.query):
            return None
        size, count = w.DWORD(), w.DWORD()
        self.api.PdhGetFormattedCounterArrayW(self.counter, 0x8200, c.byref(size), c.byref(count), None)
        if not size.value:
            return None
        buffer = c.create_string_buffer(size.value)
        if self.api.PdhGetFormattedCounterArrayW(self.counter, 0x8200, c.byref(size), c.byref(count), buffer):
            return None
        items = c.cast(buffer, c.POINTER(Item))
        engines = {}
        for index in range(count.value):
            item = items[index]
            if item.name.startswith(f'pid_{pid}_') and item.value.status in (0, 1):
                kind = item.name.split('engtype_')[-1]
                engines[kind] = engines.get(kind, 0.) + max(0., item.value.doubleValue)
        return engines or None

    def close(self):
        if self.query:
            self.api.PdhCloseQuery(self.query)
