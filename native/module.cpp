#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "queuecraft/engine.hpp"
#include <exception>
#include <stdexcept>

using queuecraft::Engine;
using queuecraft::Integer;
namespace {
constexpr const char* capsule_name = "queuecraft.Engine.v1";
Engine* engine_from(PyObject* object) {
    return static_cast<Engine*>(PyCapsule_GetPointer(object, capsule_name));
}
bool integer_from(PyObject* object, long long& value) {
    if (!PyLong_CheckExact(object)) {
        PyErr_SetString(PyExc_TypeError, "integer parameters require int, excluding bool");
        return false;
    }
    value = PyLong_AsLongLong(object);
    return !PyErr_Occurred();
}
void destroy(PyObject* capsule) {
    void* pointer = PyCapsule_GetPointer(capsule, capsule_name);
    if (pointer) delete static_cast<Engine*>(pointer);
    else PyErr_Clear();
}
PyObject* error() {
    try { throw; }
    catch (const std::overflow_error& e) { PyErr_SetString(PyExc_OverflowError, e.what()); }
    catch (const std::invalid_argument& e) { PyErr_SetString(PyExc_ValueError, e.what()); }
    catch (const std::bad_alloc&) { PyErr_NoMemory(); }
    catch (const std::exception& e) { PyErr_SetString(PyExc_RuntimeError, e.what()); }
    catch (...) { PyErr_SetString(PyExc_RuntimeError, "unknown native failure"); }
    return nullptr;
}
PyObject* csv_string(const std::string& value) {
    return PyUnicode_FromStringAndSize(value.data(), static_cast<Py_ssize_t>(value.size()));
}
PyObject* result_dict(const queuecraft::Result& result) {
    PyObject* fills = PyList_New(static_cast<Py_ssize_t>(result.fills.size()));
    if (!fills) return nullptr;
    for (std::size_t i = 0; i < result.fills.size(); ++i) {
        const auto& f = result.fills[i];
        PyObject* row = Py_BuildValue("{s:L,s:L,s:L,s:L}", "price", static_cast<long long>(f.price),
            "quantity", static_cast<long long>(f.quantity), "notional", static_cast<long long>(f.notional), "fee", static_cast<long long>(f.fee));
        if (!row) { Py_DECREF(fills); return nullptr; }
        PyList_SET_ITEM(fills, static_cast<Py_ssize_t>(i), row);
    }
    PyObject* output = Py_BuildValue("{s:N,s:L,s:L,s:L,s:L,s:L,s:L,s:L,s:L}", "fills", fills,
        "filled", static_cast<long long>(result.filled), "remaining", static_cast<long long>(result.remaining),
        "cash", static_cast<long long>(result.cash), "inventory", static_cast<long long>(result.inventory),
        "fees", static_cast<long long>(result.fees), "event", static_cast<long long>(result.event),
        "exchange_ns", static_cast<long long>(result.exchange_ns), "receive_ns", static_cast<long long>(result.receive_ns));
    return output;
}
PyObject* create(PyObject*, PyObject*) {
    try {
        auto* engine = new Engine();
        PyObject* capsule = PyCapsule_New(engine, capsule_name, destroy);
        if (!capsule) delete engine;
        return capsule;
    } catch (...) { return error(); }
}
PyObject* apply(PyObject*, PyObject* args) {
    PyObject* handle;
    const char* text;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "Os#", &handle, &text, &size)) return nullptr;
    Engine* engine = engine_from(handle);
    if (!engine) return nullptr;
    try {
        auto events = queuecraft::parse_csv(std::string_view(text, static_cast<std::size_t>(size)), false);
        if (events.size() != 1) throw std::invalid_argument("apply requires exactly one complete event");
        engine->apply(events.front());
        return csv_string(engine->snapshot());
    } catch (...) { return error(); }
}
PyObject* snapshot(PyObject*, PyObject* handle) {
    Engine* engine = engine_from(handle);
    if (!engine) return nullptr;
    try { return csv_string(engine->snapshot()); } catch (...) { return error(); }
}
PyObject* take(PyObject*, PyObject* args) {
    PyObject* handle;
    const char* side;
    long long quantity, fee = 0, liquidity = 1'000'000;
    PyObject *quantity_object, *fee_object = nullptr, *liquidity_object = nullptr;
    if (!PyArg_ParseTuple(args, "OsO|OO", &handle, &side, &quantity_object, &fee_object, &liquidity_object)) return nullptr;
    if (!integer_from(quantity_object, quantity) || (fee_object && !integer_from(fee_object, fee)) ||
        (liquidity_object && !integer_from(liquidity_object, liquidity))) return nullptr;
    Engine* engine = engine_from(handle);
    if (!engine) return nullptr;
    try { return result_dict(engine->take(side, quantity, fee, liquidity)); } catch (...) { return error(); }
}
PyObject* replay(PyObject*, PyObject* args) {
    const char* text;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "s#", &text, &size)) return nullptr;
    try { return csv_string(queuecraft::replay(std::string_view(text, static_cast<std::size_t>(size)))); }
    catch (...) { return error(); }
}
PyObject* validate(PyObject*, PyObject* args) {
    const char* text;
    Py_ssize_t size;
    if (!PyArg_ParseTuple(args, "s#", &text, &size)) return nullptr;
    try {
        auto events = queuecraft::parse_csv(std::string_view(text, static_cast<std::size_t>(size)));
        Engine engine;
        for (const auto& event : events) engine.apply(event);
        return PyLong_FromSize_t(events.size());
    } catch (...) { return error(); }
}
PyObject* decimal(PyObject*, PyObject* args) {
    const char* text;
    Py_ssize_t size;
    long long scale;
    PyObject* scale_object;
    if (!PyArg_ParseTuple(args, "s#O", &text, &size, &scale_object)) return nullptr;
    if (!integer_from(scale_object, scale)) return nullptr;
    if (scale < 0 || scale > 18) { PyErr_SetString(PyExc_ValueError, "scale must be 0..18"); return nullptr; }
    try { return PyLong_FromLongLong(queuecraft::parse_decimal(std::string_view(text, static_cast<std::size_t>(size)), static_cast<int>(scale))); }
    catch (...) { return error(); }
}
PyObject* execute(PyObject*, PyObject* args) {
    const char* text;
    Py_ssize_t size;
    const char* side;
    long long quantity, latency = 0, fee = 0, liquidity = 1'000'000;
    PyObject *quantity_object, *latency_object = nullptr, *fee_object = nullptr, *liquidity_object = nullptr;
    if (!PyArg_ParseTuple(args, "s#sO|OOO", &text, &size, &side, &quantity_object, &latency_object, &fee_object, &liquidity_object)) return nullptr;
    if (!integer_from(quantity_object, quantity) || (latency_object && !integer_from(latency_object, latency)) ||
        (fee_object && !integer_from(fee_object, fee)) || (liquidity_object && !integer_from(liquidity_object, liquidity))) return nullptr;
    try { return result_dict(queuecraft::execute(std::string_view(text, static_cast<std::size_t>(size)), side, quantity, latency, fee, liquidity)); }
    catch (...) { return error(); }
}
PyMethodDef methods[] = {
    {"create", create, METH_NOARGS, "Create a single-thread-owned execution state."},
    {"apply", apply, METH_VARARGS, "Atomically apply exactly one complete normalized event CSV."},
    {"snapshot", snapshot, METH_O, "Complete recorded book CSV at the current event."},
    {"take", take, METH_VARARGS, "Execute hypothetical IOC against recorded-minus-consumed depth."},
    {"replay", replay, METH_VARARGS, "Return complete level traces for bounded normalized input."},
    {"validate", validate, METH_VARARGS, "Strictly validate original CSV bytes and all book transitions, returning event count."},
    {"parse_decimal", decimal, METH_VARARGS, "Parse exact fixed point with scale decimal places."},
    {"execute", execute, METH_VARARGS, "One immediate IOC with explicit observation-to-arrival latency."},
    {nullptr, nullptr, 0, nullptr}
};
PyModuleDef module = {PyModuleDef_HEAD_INIT, "_native", "QueueCraft C++20 engine, ABI v1.", -1, methods, nullptr, nullptr, nullptr, nullptr};
}
PyMODINIT_FUNC PyInit__native() { return PyModule_Create(&module); }
