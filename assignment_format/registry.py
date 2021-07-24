from django.utils import six

formats = {}


def register_assignment_format(name):
    def register_class(assignment_format_class):
        assert name not in formats
        formats[name] = assignment_format_class
        return assignment_format_class

    return register_class


def choices():
    return [(key, value.name) for key, value in sorted(six.iteritems(formats))]
