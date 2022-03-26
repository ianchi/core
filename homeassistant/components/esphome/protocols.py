# Protocol Registry
#
# all platforms should implement a consistent definition

import codecs
import pathlib
import re

import voluptuous as vol
import yaml

PROTOCOLS_YAML = "protocols.yaml"

# cache protocols definitions and schemas
PROTO_CACHE = {}
PROTO_DEF = "proto_def"
PROTO_SCHEMA = "proto_schema"
VALID_PROTOCOLS = "valid_protocols"


# Validation Helpers
# Borrewed from cv to use exactly the same in Home Assistant


def string(value):
    """Validate that a configuration value is a string. If not, automatically converts to a string.

    Note that this can be lossy, for example the input value 60.00 (float) will be turned into
    "60.0" (string). For values where this could be a problem `string_string` has to be used.
    """
    if isinstance(value, (dict, list)):
        raise vol.Invalid("string value cannot be dictionary or list.")
    if isinstance(value, bool):
        raise vol.Invalid(
            "Auto-converted this value to boolean, please wrap the value in quotes."
        )
    if isinstance(value, str):
        # remove quotes
        re_quote = re.compile(r"^\s*([\"\'])((?:(?!\1).|\\\1)*)(?<!\\)\1\s*$")
        # remove border quotes
        m = re.search(re_quote, value)
        if m:
            value = m[2]
        return value
    if value is not None:
        return str(value)
    raise vol.Invalid("string value is None")


def string_strict(value):
    """Like string, but only allows strings, and does not automatically convert other types to
    strings."""
    if isinstance(value, str):
        return value
    raise vol.Invalid(
        f"Must be string, got {type(value)}. did you forget putting quotes around the value?"
    )


def integer(value):
    """Validate that the config option is an integer.

    Automatically also converts strings to ints.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if int(value) == value:
            return int(value)
        raise vol.Invalid(
            f"This option only accepts integers with no fractional part. Please remove the fractional part from {value}"
        )
    value = string_strict(value).lower()
    base = 10
    if value.startswith("0x"):
        base = 16
    try:
        return int(value, base)
    except ValueError:
        # pylint: disable=raise-missing-from
        raise vol.Invalid(f"Expected integer, but cannot parse {value} as an integer")


def integer_range(min=None, max=None, min_included=True, max_included=True):
    """Validate that the config option is an integer in the given range."""
    if min is not None:
        assert isinstance(min, int)
    if max is not None:
        assert isinstance(max, int)
    return vol.All(
        integer,
        vol.Range(
            min=min, max=max, min_included=min_included, max_included=max_included
        ),
    )


def valid(value):
    """A validator that is always valid and returns the value as-is."""
    return value


def unique_field_value(field):
    def validator(value):
        vol.Schema(vol.Unique())([a[field] for a in value])

        return value

    return validator


def coerce_list(value):

    if isinstance(value, list):
        return value

    if value is None:
        return []

    if isinstance(value, str):
        return quoted_split(value, ",")

    return [value]


valid_name = vol.All(
    string_strict,
    vol.Match(
        r"^[a-zA-Z_][a-zA-Z0-9_]*$",
        msg="Invalid characters for an identifier name",
    ),
)


def kebab_to_pascal(value):

    value = string_strict(value)

    value = "".join([w.title() for w in value.split("_")])
    return value


def alternating_signs(value):
    assert isinstance(value, list)
    last_negative = None
    for i, val in enumerate(value):
        this_negative = val < 0
        if i != 0:
            if this_negative == last_negative:
                raise vol.Invalid(
                    f"Values must alternate between being positive and negative, please see index {i} and {i + 1}",
                    [i],
                )
        last_negative = this_negative
    return value


def binary_string(value):

    value = string(value)

    for char in value:
        if char not in ("0", "1"):
            raise vol.Invalid(f"String must be all binary digits, but got '{char}'")

    return value


#

CPP_TYPES = {
    "int": integer_range(min=-2147483648, max=2147483647),
    "int32_t": integer_range(min=-2147483648, max=2147483647),
    "uint": integer_range(min=0, max=4294967295),
    "uint8_t": integer_range(min=0, max=255),
    "uint16_t": integer_range(min=0, max=65535),
    "uint32_t": integer_range(min=0, max=4294967295),
    "uint64_t": integer_range(min=0, max=18446744073709551615),
    "float": vol.Coerce(float),
    "bool": vol.Boolean,
    "string": string,
}

VALID_TYPES = list(CPP_TYPES) + [t + "[]" for t in CPP_TYPES]

# protocols.yaml validation

SCHEMA_VALIDATORS = {
    # Voluptuous
    "Range": vol.Range,
    "Any": vol.Any,
    "Length": vol.Length,
    # Custom
    "proto_pronto": valid,  # TODO
    "alternating_signs": alternating_signs,
    "binary_string": binary_string,
}

SCHEMA_SCHEMA = vol.Schema(
    {
        vol.Any(*list(SCHEMA_VALIDATORS)): vol.Any(
            [valid], vol.Schema({}, extra=True), None
        )
    }
)


def generate_arg_schema(arg):
    # get type validator
    arg_type = arg["type"]
    if arg_type[-2:] == "[]":
        type_cv = vol.All(coerce_list, [CPP_TYPES[arg_type[:-2]]])
    else:
        type_cv = CPP_TYPES[arg_type]
    val = [type_cv]

    # add optional extra validators
    if "schema" in arg:

        for cv, a in arg["schema"].items():

            if a is None:
                # validator without argument
                val.append(SCHEMA_VALIDATORS[cv])
            elif isinstance(a, list):
                # direct positional argument list
                val.append(SCHEMA_VALIDATORS[cv](*a))
            elif isinstance(a, dict):
                # dict of arguments

                if "args" in a and isinstance(a["args"], list):
                    # dict + positional
                    posargs = a["args"]
                    del a["args"]
                else:
                    posargs = []

                val.append(SCHEMA_VALIDATORS[cv](*posargs, **a))

    if len(val) == 1:
        val = val[0]
    else:
        val = vol.All(*val)

    return val


def validate_default(arg):

    if "default" not in arg:
        return arg

    val = generate_arg_schema(arg)

    try:
        arg["default"] = val(arg["default"])
        return arg
    except vol.Invalid as err:
        raise vol.Invalid(
            f"Error in default value for argument <{arg['name']}> {err.msg}"
        )


ARGS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("name"): valid_name,
            vol.Required("type"): vol.Any(*VALID_TYPES),
            vol.Required("desc"): string,
            vol.Optional("default"): valid,
            vol.Optional("example"): string,
            vol.Optional("schema"): SCHEMA_SCHEMA,
        }
    ),
    validate_default,
)

PROTOCOL_DEF_SCHEMA = vol.Schema(
    {
        vol.Required("desc"): string,
        vol.Required("type"): vol.Any("IR", "RF", "IR/RF"),
        vol.Optional("link"): [vol.Url],
        vol.Optional("note"): string,
        vol.Required("args"): vol.All(
            [ARGS_SCHEMA], vol.Length(min=1), unique_field_value("name")
        ),
    },
)

PROTOCOLS_SCHEMA = vol.Schema({valid_name: PROTOCOL_DEF_SCHEMA})


def load_protocols():

    path = pathlib.Path(__file__).parent.resolve()

    with codecs.open(path / PROTOCOLS_YAML, "r", encoding="utf-8") as f_handle:
        proto_yaml = yaml.safe_load(f_handle)

    # validate file - first pass (without defaults)
    PROTOCOLS_SCHEMA(proto_yaml)

    return proto_yaml


def dict_to_list(keys):
    def converter(value):
        return [value[k] for k in keys]

    return converter


def generate_proto_schema(protocols):
    """Generate Voluptuous Schema dynamically to validate arguments of each protocol
    according to yaml definition
    """

    schemas = {}

    for proto_name, proto_def in protocols.items():

        schemas[proto_name] = {}
        names = []
        for arg in proto_def["args"]:
            if "default" in arg:
                key = vol.Optional(arg["name"], default=arg["default"])
            else:
                key = vol.Required(arg["name"])
            names.append(arg["name"])

            schemas[proto_name][key] = generate_arg_schema(arg)

        schemas[proto_name] = vol.All(
            # validate as dict to get argument name info on errors
            vol.Schema(schemas[proto_name]),
            # convert value to list in expected order for program handling
            dict_to_list(names),
        )

    return schemas


# Values validation


def quoted_split(text, delimiter):
    """Splits a string by 'delimiter', ignoring it if it is inside quotations
    Returns a list of strings with results.
    Consecutive delimiters are returned as empty string
    """

    args = []
    # gets first part
    re_first = re.compile(
        r"^(?:\s*([\"\'])(?:(?!\1).|\\\1)*(?<!\\)\1\s*|[^" + delimiter + r"]?)+"
    )

    while len(text):
        m = re.search(re_first, text)

        text = text[m.end(0) + 1 :]

        # remove spaces
        arg = m[0].strip()

        args.append(arg)

    return args


def get_proto_def(proto_name):

    validate_protocol_name(proto_name)

    return PROTO_CACHE[PROTO_DEF][proto_name]


def get_proto_signature(proto_name):

    arg_def = get_proto_def(proto_name)["args"]

    declaration = [proto_name]

    for arg in arg_def:

        name = f"{arg['type'].replace('_t', '')} {arg['name']}"

        if "default" in arg:
            declaration.append(f"<{name}?={arg['default']}>")
        else:
            declaration.append(f"<{name}>")

    return ":".join(declaration)


def args_to_dict(proto, args):
    """Converts an argument list into a dict using predefined parameters names as keys.
    Empty parameters will be missing keys.
    """

    proto_def = get_proto_def(proto)

    result = {}

    if len(proto_def["args"]) < len(args):
        raise vol.Invalid(
            f"Expected maximum {len(proto_def['args'])} arguments for protocol '{proto}'"
        )

    for i, arg in enumerate(args):
        result[proto_def["args"][i]["name"]] = arg

    return result


def validate_protocol_name(proto_name):

    string_strict(proto_name)
    proto_name = proto_name.lower()

    if PROTO_DEF not in PROTO_CACHE:
        raise vol.Invalid("Protocols not initialized")

    if proto_name not in PROTO_CACHE[PROTO_DEF]:
        raise vol.Invalid(f"Protocol '{proto_name}' is not defined")

    return proto_name


def validate_send_command(command):
    """Validates a command string according to proto definition
    and returns a command object with the parsed protocol & arguments (including any defaults)
    """

    command = string_strict(command)
    command_list = quoted_split(command, ":")

    if len(command_list) <= 1:
        raise vol.Invalid(
            "Command string needs to have at least a protocol and a parameter list"
        )

    return validate_command({"protocol": command_list[0], "args": command_list[1:]})


def validate_command(command):
    """Validates a command object (protocol & arguments list)"""

    command = vol.Schema(
        {
            vol.Required("protocol"): validate_protocol_name,
            vol.Required("args"): vol.Length(min=1),
        }
    )(command)
    try:
        args = args_to_dict(command["protocol"], command["args"])

        command["args"] = PROTO_CACHE[PROTO_SCHEMA][command["protocol"]](args)
        return command

    except vol.Invalid as err:
        signature = get_proto_signature(command["protocol"])
        if err.path:
            path = f"<{err.path[-1]}>: "
        else:
            path = ""
        raise vol.Invalid(
            f"Malformatted command for protocol '{command['protocol']}'.\n"
            f"Expected:   {signature}\n"
            f"Received:   {command}\n"
            f"ERROR:      {path}{err.msg}",
        )


def initialize():
    PROTO_CACHE[PROTO_DEF] = load_protocols()
    PROTO_CACHE[PROTO_SCHEMA] = generate_proto_schema(PROTO_CACHE[PROTO_DEF])
    PROTO_CACHE[VALID_PROTOCOLS] = list(PROTO_CACHE[PROTO_DEF])


initialize()
