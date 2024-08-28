import sys

mock_registry = {}
patch_registry = {}


class core_mock(object):
    '''
    This functor creates the decorators that are used to register the mocks
    when the litpats.mocking.mocks module is imported.
    '''

    def __init__(self, mock_qual_name):
        self.qual_name = mock_qual_name

    def __call__(self, mock_callable):
        if self.qual_name in mock_registry:
            raise SystemError(
                "A mock is already registered for \"%s\"" % self.qual_name
            )
        mock_registry[self.qual_name] = mock_callable


class core_patch(object):
    '''
    This functor creates the decorators that are used to register the patches
    when the litpats.mocking.patches module is imported.
    '''

    def __init__(self, patch_qual_name):
        self.qual_name = patch_qual_name

    def __call__(self, patch_callable):
        if self.qual_name in patch_registry:
            raise SystemError(
                "A patch is already registered for \"%s\"" % self.qual_name
            )
        patch_registry[self.qual_name] = patch_callable


def _resolve_qual_name(qual_name):
    module_path_tokens = list(qual_name.split("."))
    target_module_attributes = []

    target_module = None
    while module_path_tokens:
        # Can we import this?
        qualified_name = ".".join(module_path_tokens)

        try:
            target_module = __import__(qualified_name)
            break

        except ImportError:
            target_module_attributes.append(module_path_tokens.pop())

    if not target_module or qualified_name not in sys.modules:
        raise SystemError("Couldn't import module \"%s\"" % qualified_name)

    target_module = sys.modules[qualified_name]
    target_module_attributes.reverse()

    target_object = target_module
    target_attribute_bearer = None
    attr_name = None
    for attr_name in target_module_attributes:
        try:
            target_attribute_bearer = target_object
            target_object = getattr(target_object, attr_name)
        except AttributeError:
            raise SystemError(
                "Couldn't dereference attribute \"%s\" of \"%s\"" % \
                    (attr_name, target_object)
            )

    return target_attribute_bearer, attr_name, \
        getattr(target_attribute_bearer, attr_name)


def _mock_core_callable(qual_name, mock):
    attr_bearer, attr_to_mock, _ = _resolve_qual_name(qual_name)
    setattr(attr_bearer, attr_to_mock, mock)


def _patch_core_callable(qual_name, decorator):
    attr_bearer, attr_to_mock, attr = _resolve_qual_name(qual_name)
    setattr(
        attr_bearer,
        attr_to_mock,
        decorator(attr)
    )


def enable_core_bypass():

    clashes = set(mock_registry) & set(patch_registry)
    if clashes:
        raise SystemError("Clashing mocks and patches for: \"%s\"" % clashes)

    for mock_qual_name, mock_callable in mock_registry.iteritems():
        _mock_core_callable(mock_qual_name, mock_callable)

    for patch_qual_name, patch_callable in patch_registry.iteritems():
        _patch_core_callable(patch_qual_name, patch_callable)

    # Ensures calls to methods decorated with the @background decorator are
    # run synchronously in the calling thread.
    #
    # Note: We want to avoid importing a core module as doing so will break
    # documentation generation at build time
    threadpool_module, _, _ = _resolve_qual_name(
        'litp.core.litp_threadpool._set_mock'
    )
    getattr(threadpool_module, '_set_mock')()
