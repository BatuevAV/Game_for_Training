#!/bin/bash
# Удобные алиасы для управления проектом Комарики

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

case "$1" in
    "users")
        echo -e "${GREEN}📋 Список всех пользователей${NC}"
        $VENV_PYTHON "$SCRIPT_DIR/list_users.py"
        ;;
    "find")
        if [ -z "$2" ]; then
            echo "Использование: ./manage.sh find <user_id|telegram_id|username>"
            echo "Примеры:"
            echo "  ./manage.sh find 1"
            echo "  ./manage.sh find 997743143"
            echo "  ./manage.sh find sankaapelsin"
            exit 1
        fi
        
        # Определяем тип параметра
        if [[ "$2" =~ ^[0-9]+$ ]]; then
            # Если число от 1 до 999, вероятно это user_id
            if [ "$2" -lt 1000 ]; then
                echo -e "${GREEN}🔍 Поиск по User ID: $2${NC}"
                $VENV_PYTHON "$SCRIPT_DIR/find_user.py" --user-id "$2"
            else
                echo -e "${GREEN}🔍 Поиск по Telegram ID: $2${NC}"
                $VENV_PYTHON "$SCRIPT_DIR/find_user.py" --telegram-id "$2"
            fi
        else
            echo -e "${GREEN}🔍 Поиск по username: $2${NC}"
            $VENV_PYTHON "$SCRIPT_DIR/find_user.py" --username "$2"
        fi
        ;;
    "check")
        if [ -z "$2" ]; then
            echo "Использование: ./manage.sh check <telegram_id>"
            echo "Пример: ./manage.sh check 997743143"
            exit 1
        fi
        echo -e "${GREEN}✅ Проверка пользователя $2${NC}"
        $VENV_PYTHON "$SCRIPT_DIR/check_user.py" "$2"
        ;;
    "premium")
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "Использование: ./manage.sh premium <telegram_id> <on|off>"
            echo "Примеры:"
            echo "  ./manage.sh premium 997743143 on   # Включить Premium"
            echo "  ./manage.sh premium 997743143 off  # Выключить Premium"
            exit 1
        fi
        
        if [ "$3" == "on" ]; then
            echo -e "${YELLOW}⭐ Активация Premium для $2${NC}"
            $VENV_PYTHON "$SCRIPT_DIR/update_premium.py" "$2" true
        elif [ "$3" == "off" ]; then
            echo -e "${YELLOW}❌ Деактивация Premium для $2${NC}"
            $VENV_PYTHON "$SCRIPT_DIR/update_premium.py" "$2" false
        else
            echo "Ошибка: используйте 'on' или 'off'"
            exit 1
        fi
        ;;
    "server")
        echo -e "${GREEN}🚀 Запуск сервера...${NC}"
        cd "$SCRIPT_DIR"
        "$SCRIPT_DIR/venv/bin/uvicorn" testik.api:app --reload --host 0.0.0.0 --port 8000
        ;;
    "admin")
        echo -e "${GREEN}🔧 Открытие админ-панели...${NC}"
        echo "Админ-панель доступна по адресу: http://127.0.0.1:8000/admin"
        if command -v open &> /dev/null; then
            open "http://127.0.0.1:8000/admin"
        elif command -v xdg-open &> /dev/null; then
            xdg-open "http://127.0.0.1:8000/admin"
        fi
        ;;
    "migrate")
        echo -e "${GREEN}📦 Применение миграций...${NC}"
        cd "$SCRIPT_DIR"
        "$SCRIPT_DIR/venv/bin/alembic" upgrade head
        ;;
    "help"|"")
        echo -e "${GREEN}🦟 Утилита управления проектом Комарики${NC}"
        echo ""
        echo "Использование: ./manage.sh <команда> [параметры]"
        echo ""
        echo "Команды:"
        echo "  users              - Показать всех пользователей"
        echo "  find <id>          - Найти пользователя (User ID, Telegram ID или username)"
        echo "  check <telegram_id>- Проверить статус пользователя"
        echo "  premium <id> on/off- Управление Premium подпиской"
        echo "  server             - Запустить FastAPI сервер"
        echo "  admin              - Открыть админ-панель в браузере"
        echo "  migrate            - Применить миграции БД"
        echo "  help               - Показать эту справку"
        echo ""
        echo "Примеры:"
        echo "  ./manage.sh users"
        echo "  ./manage.sh find 1"
        echo "  ./manage.sh find sankaapelsin"
        echo "  ./manage.sh check 997743143"
        echo "  ./manage.sh premium 997743143 on"
        echo "  ./manage.sh server"
        ;;
    *)
        echo "Неизвестная команда: $1"
        echo "Используйте './manage.sh help' для справки"
        exit 1
        ;;
esac
