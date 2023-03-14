class CustomCodeException(Exception):
    def __init__(self, message, code, description=None):
        self.message = message
        self.code = code
        self.description = description

    def __str__(self):
        if self.description:
            return f'{self.code}: {self.message}; {self.description}'
        else:
            return f'{self.code}: {self.message}'

ERROR_IN_LOGICAL_SQL = ('Error in Logical Sql', 65001)
ERROR_IN_ADDITIONAL_PARAMETERS = ('Error in Additional Parameters', 65002)
