"""Зарезервированные слова X++ (Microsoft Dynamics AX 2012).

Список нельзя использовать как ИМЯ поля/локальной переменной/параметра — компилятор
AX выдаст синтаксическую ошибку. Использование в других позициях (например как часть
более длинного идентификатора: `serverUrl`, `sessionId`) допустимо — конфликт только
при точном совпадении целого слова.

Источник — реальный экспортированный список зарезервированных слов Axapta
(docs/Reserved.txt в проекте LT_AxaptaMCPServer), сверено с официальной
документацией Microsoft (X++ Keywords, learn.microsoft.com/dynamicsax-2012).
Сравнение регистронезависимое (X++ ключевые слова не чувствительны к регистру).
"""

RESERVED_WORDS = frozenset(w.lower() for w in (
    "abstract", "anytype", "as", "asc", "avg", "breakpoint", "by", "case",
    "changecompany", "class", "client", "commit", "container", "count",
    "crosscompany", "date", "default", "delegate", "delete_from", "desc",
    "display", "div", "do", "dynamic", "edit", "else", "enter", "enum",
    "eventhandler", "exists", "false", "final", "firstfast", "firstonly",
    "firstonly10", "firstonly100", "firstonly1000", "for", "forceliterals",
    "forcenestedloop", "forceplaceholders", "forceselectorder", "from", "guid",
    "if", "in", "index", "insert_recordset", "int", "int64", "interface",
    "is", "join", "leave", "like", "maxof", "minof", "mod", "new", "nofetch",
    "notexists", "null", "optimisticlock", "order", "outer", "pessimisticlock",
    "print", "private", "protected", "public", "real", "repeatableread",
    "retry", "return", "reverse", "select", "server", "setting", "static",
    "str", "sum", "super", "switch", "this", "throw", "true", "try",
    "ttsbegin", "ttscommit", "ttsabort", "update_recordset", "utcdatetime",
    "validtimestate", "void", "while", "window",
))
