#!/usr/bin/env bash
set -Eeuo pipefail

# Р¦РІРµС‚РѕРІР°СЏ РїР°Р»РёС‚СЂР°
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# РќР°СЃС‚СЂРѕР№РєРё РїСЂРѕРµРєС‚Р°
PROJECT_NAME="remnawave-shopbot"
# FIX: СЂР°РЅСЊС€Рµ РїСѓС‚СЊ Р±С‹Р» РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅС‹Рј Рё СѓРґР°Р»РµРЅРёРµ РЅРµ РЅР°С…РѕРґРёР»Рѕ РїСЂРѕРµРєС‚,
# РµСЃР»Рё СЃРєСЂРёРїС‚ Р·Р°РїСѓСЃРєР°Р»СЃСЏ РЅРµ РёР· $HOME
PROJECT_DIR="$HOME/$PROJECT_NAME"
if [[ ! -d "$PROJECT_DIR" ]] && [[ -d "./$PROJECT_NAME" ]]; then
    PROJECT_DIR="$(pwd)/$PROJECT_NAME"
fi
NGINX_CONF="/etc/nginx/sites-available/${PROJECT_NAME}.conf"
NGINX_LINK="/etc/nginx/sites-enabled/${PROJECT_NAME}.conf"

# РџРµСЂРµРјРµРЅРЅС‹Рµ СѓРґР°Р»РµРЅРёСЏ
REMOVE_CONFIG=false
REMOVE_DOCKER=false
REMOVE_PROJECT=false
REMOVE_CERTBOT=false
REMOVE_SSL=false
REMOVE_ALL=false
local_db_backup=""

# --- Р¤СѓРЅРєС†РёРё РѕС‚РѕР±СЂР°Р¶РµРЅРёСЏ ---

show_header() {
    clear
    echo -e "${PURPLE}${BOLD}в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ${NC}"
    echo -e "${PURPLE}${BOLD}        REMNAWAVE SHOPBOT UNINSTALLER (РЈРґР°Р»РµРЅРёРµ)             ${NC}"
    echo -e "${PURPLE}${BOLD}в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ${NC}"
    echo ""
}

show_footer() {
    echo -e "${CYAN}${BOLD}в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ${NC}"
    echo -e "${CYAN}Р РµРїРѕР·РёС‚РѕСЂРёР№:${NC}  https://github.com/CyberERROR/remnawave-shopbot"
    echo -e "${CYAN}Telegram:${NC}      https://t.me/+7hUhNxAdzBpjNWRi"
    echo -e "${CYAN}Р Р°Р·СЂР°Р±РѕС‚С‡РёРє:${NC}   https://github.com/CyberERROR"
    echo -e "${CYAN}${BOLD}в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ${NC}"
    echo ""
}

log_info() {
    echo -e "${BLUE}${BOLD}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}${BOLD}[вњ”]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}${BOLD}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}${BOLD}[вњ] РћС€РёР±РєР°:${NC} $1" >&2
}

log_input() {
    echo -ne "${CYAN}${BOLD}[?]${NC} $1"
}

# Р¤СѓРЅРєС†РёСЏ СЃРїРёРЅРЅРµСЂР° СЃ РёРЅС„РѕСЂРјР°С†РёРµР№ Рѕ РїСЂРѕС†РµСЃСЃРµ
run_with_spinner() {
    local message="$1"
    shift
    local cmd=("$@")

    echo -ne "${BLUE}${BOLD}[вћњ]${NC} ${message}... "

    local temp_log
    temp_log=$(mktemp)
    
    # Р—Р°РїСѓСЃРєР°РµРј РєРѕРјР°РЅРґСѓ
    if "${cmd[@]}" > "$temp_log" 2>&1; then
        echo -e "${GREEN}${BOLD}OK${NC}"
        rm -f "$temp_log"
        return 0
    else
        local exit_code=$?
        echo -e "${RED}${BOLD}FAILED${NC}"
        echo -e "\n${RED}================ LOG OUTPUT =================${NC}"
        cat "$temp_log"
        echo -e "${RED}=============================================${NC}"
        rm -f "$temp_log"
        return $exit_code
    fi
}

on_error() {
    echo ""
    log_error "РЎРєСЂРёРїС‚ РїСЂРµСЂРІР°РЅ РЅР° СЃС‚СЂРѕРєРµ $1."
    exit 1
}
trap 'on_error $LINENO' ERR

# --- РћСЃРЅРѕРІРЅС‹Рµ С„СѓРЅРєС†РёРё СѓРґР°Р»РµРЅРёСЏ ---

ensure_sudo_refresh() {
    if ! sudo -v; then
        log_error "РўСЂРµР±СѓСЋС‚СЃСЏ РїСЂР°РІР° sudo. Р’РІРµРґРёС‚Рµ РїР°СЂРѕР»СЊ РІС‹С€Рµ."
        exit 1
    fi
}
show_menu() {
    echo ""
    echo -e "${YELLOW}${BOLD}Р§С‚Рѕ РІС‹ С…РѕС‚РёС‚Рµ СѓРґР°Р»РёС‚СЊ?${NC}"
    echo ""
    echo -e " ${CYAN}1)${NC} РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx Рё СЃРµСЂС‚РёС„РёРєР°С‚С‹ (${CYAN}Р±С‹СЃС‚СЂРѕРµ СѓРґР°Р»РµРЅРёРµ${NC})"
    echo -e " ${CYAN}2)${NC} РџРѕР»РЅРѕРµ СѓРґР°Р»РµРЅРёРµ РїСЂРёР»РѕР¶РµРЅРёСЏ (РєРѕРЅС„РёРі + РїСЂРѕРµРєС‚ + РєРѕРЅС‚РµР№РЅРµСЂС‹)"
    echo -e " ${CYAN}3)${NC} РњР°РєСЃРёРјР°Р»СЊРЅРѕРµ СѓРґР°Р»РµРЅРёРµ (РІСЃС‘ + Certbot + Р·Р°РІРёСЃРёРјРѕСЃС‚Рё)"
    echo -e " ${CYAN}4)${NC} РќР°СЃС‚СЂРѕРёС‚СЊ РІСЂСѓС‡РЅСѓСЋ"
    echo -e " ${CYAN}0)${NC} РћС‚РјРµРЅР°"
    echo ""
    log_input "Р’С‹Р±РµСЂРёС‚Рµ РІР°СЂРёР°РЅС‚ [0-4] (default: 0): "
    read -r -n1 CHOICE < /dev/tty || true
    echo ""
    
    if [[ -z "$CHOICE" ]]; then
        CHOICE=0
    fi
    
    case "$CHOICE" in
        1)
            REMOVE_CONFIG=true
            REMOVE_SSL=true
            ;;
        2)
            REMOVE_CONFIG=true
            REMOVE_DOCKER=true
            REMOVE_PROJECT=true
            REMOVE_SSL=true
            ;;
        3)
            REMOVE_ALL=true
            REMOVE_CONFIG=true
            REMOVE_DOCKER=true
            REMOVE_PROJECT=true
            REMOVE_SSL=true
            REMOVE_CERTBOT=true
            ;;
        4)
            show_custom_menu
            ;;
        0)
            log_error "РЈРґР°Р»РµРЅРёРµ РѕС‚РјРµРЅРµРЅРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»РµРј."
            exit 0
            ;;
        *)
            log_warn "РќРµРІРµСЂРЅС‹Р№ РІС‹Р±РѕСЂ. РћС‚РјРµРЅР°."
            exit 1
            ;;
    esac
    
    # РџРµСЂРµРґ СѓРґР°Р»РµРЅРёРµРј РєР°С‚Р°Р»РѕРіР° РїСЂРѕРµРєС‚Р°: СЃРѕС…СЂР°РЅРёС‚СЊ Р‘Р” Рё Р±СЌРєР°РїС‹?
    if [[ "$REMOVE_PROJECT" == "true" && -d "$PROJECT_DIR" ]]; then
        if [[ -f "$PROJECT_DIR/users.db" ]]; then
            log_input "РЎРѕС…СЂР°РЅРёС‚СЊ РєРѕРїРёСЋ Р‘Р” (users.db) РїРµСЂРµРґ СѓРґР°Р»РµРЅРёРµРј РІ ~/? (Y/n): "
            read -r -n1 REPLY < /dev/tty || true
            echo ""
            if [[ -z "$REPLY" ]] || [[ "$REPLY" =~ [yY] ]]; then
                local_db_backup="$HOME/users-backup-$(date +%Y%m%d-%H%M%S).db"
                if cp "$PROJECT_DIR/users.db" "$local_db_backup" 2>/dev/null; then
                    log_success "Р‘Р” СЃРѕС…СЂР°РЅРµРЅР°: $local_db_backup"
                else
                    log_warn "РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєРѕРїРёСЂРѕРІР°С‚СЊ Р‘Р”"
                    local_db_backup=""
                fi
            fi
        fi
        if compgen -G "$PROJECT_DIR/backups/db-backup-*.zip" >/dev/null 2>&1; then
            log_input "РЎРѕС…СЂР°РЅРёС‚СЊ Р°СЂС…РёРІС‹ Р±СЌРєР°РїРѕРІ (СЃРЅРёРјРєРё Remnawave) РІ ~/shopbot-backups/? (y/N): "
            read -r -n1 REPLY < /dev/tty || true
            echo ""
            if [[ "$REPLY" =~ [yY] ]]; then
                mkdir -p "$HOME/shopbot-backups"
                cp "$PROJECT_DIR"/backups/db-backup-*.zip "$HOME/shopbot-backups/" 2>/dev/null || true
                cp "$PROJECT_DIR"/backups/*.manifest.json "$HOME/shopbot-backups/" 2>/dev/null || true
                log_success "РђСЂС…РёРІС‹ Р±СЌРєР°РїРѕРІ СЃРѕС…СЂР°РЅРµРЅС‹ РІ ~/shopbot-backups/"
            fi
        fi
    fi
}

show_custom_menu() {
    echo ""
    echo -e "${YELLOW}${BOLD}Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ РѕРїС†РёРё СѓРґР°Р»РµРЅРёСЏ:${NC}"
    echo ""
    
    # РљРѕРЅС„РёРі Nginx
    if [[ -f "$NGINX_CONF" ]] || [[ -L "$NGINX_LINK" ]]; then
        log_input "РЈРґР°Р»РёС‚СЊ РєРѕРЅС„РёРіСѓСЂР°С†РёСЋ Nginx? (Y/n): "
        read -r -n1 REPLY < /dev/tty || true
        echo ""
        if [[ -z "$REPLY" ]] || [[ "$REPLY" =~ [yY] ]]; then
            REMOVE_CONFIG=true
        fi
    fi
    
    # РЎРµСЂС‚РёС„РёРєР°С‚С‹ SSL
    DOMAIN=$(get_domain_from_nginx || echo "")
    if [[ -n "$DOMAIN" ]] && [[ -d "/etc/letsencrypt/live/${DOMAIN}" ]]; then
        log_input "РЈРґР°Р»РёС‚СЊ SSL СЃРµСЂС‚РёС„РёРєР°С‚С‹ РґР»СЏ $DOMAIN? (Y/n): "
        read -r -n1 REPLY < /dev/tty || true
        echo ""
        if [[ -z "$REPLY" ]] || [[ "$REPLY" =~ [yY] ]]; then
            REMOVE_SSL=true
        fi
    fi
    
    # Docker РєРѕРЅС‚РµР№РЅРµСЂС‹
    if command -v docker >/dev/null 2>&1 && docker ps -a 2>/dev/null | grep -q "$PROJECT_DIR"; then
        log_input "РћСЃС‚Р°РЅРѕРІРёС‚СЊ Рё СѓРґР°Р»РёС‚СЊ Docker РєРѕРЅС‚РµР№РЅРµСЂС‹? (Y/n): "
        read -r -n1 REPLY < /dev/tty || true
        echo ""
        if [[ -z "$REPLY" ]] || [[ "$REPLY" =~ [yY] ]]; then
            REMOVE_DOCKER=true
        fi
    fi
    
    # РљР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р°
    if [[ -d "$PROJECT_DIR" ]]; then
        log_input "РЈРґР°Р»РёС‚СЊ РєР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° ($PROJECT_DIR)? (y/N): "
        read -r -n1 REPLY < /dev/tty || true
        echo ""
        if [[ "$REPLY" =~ [yY] ]]; then
            REMOVE_PROJECT=true
        fi
    fi
    
    # Certbot
    if command -v certbot >/dev/null 2>&1; then
        log_input "РЈРґР°Р»РёС‚СЊ Certbot? (y/N): "
        read -r -n1 REPLY < /dev/tty || true
        echo ""
        if [[ "$REPLY" =~ [yY] ]]; then
            REMOVE_CERTBOT=true
        fi
    fi
}

get_domain_from_nginx() {
    if [[ -f "$NGINX_CONF" ]]; then
        grep "server_name" "$NGINX_CONF" | awk '{print $2}' | sed 's/;//' | head -n1
    fi
}

show_removal_summary() {
    echo ""
    echo -e "${YELLOW}${BOLD}в”Ѓв”Ѓв”Ѓв”Ѓ РС‚РѕРіРѕРІС‹Р№ СЃРїРёСЃРѕРє СѓРґР°Р»РµРЅРёСЏ в”Ѓв”Ѓв”Ѓв”Ѓ${NC}"
    echo ""
    
    [[ "$REMOVE_CONFIG" == "true" ]] && echo -e " ${RED}вњ${NC} РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx"
    [[ "$REMOVE_SSL" == "true" ]] && echo -e " ${RED}вњ${NC} SSL СЃРµСЂС‚РёС„РёРєР°С‚С‹"
    [[ "$REMOVE_DOCKER" == "true" ]] && echo -e " ${RED}вњ${NC} Docker РєРѕРЅС‚РµР№РЅРµСЂС‹ Рё РѕР±СЂР°Р·С‹"
    [[ "$REMOVE_PROJECT" == "true" ]] && echo -e " ${RED}вњ${NC} РљР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° ($PROJECT_DIR)"
    [[ "$REMOVE_CERTBOT" == "true" ]] && echo -e " ${RED}вњ${NC} Certbot"
    
    echo ""
    log_input "Р’С‹ СѓРІРµСЂРµРЅС‹? Р­С‚Рѕ РґРµР№СЃС‚РІРёРµ РЅРµРІРѕР·РјРѕР¶РЅРѕ РѕС‚РјРµРЅРёС‚СЊ! (y/N): "
    read -r -n1 CONFIRM < /dev/tty || true
    echo ""
    
    if [[ ! "$CONFIRM" =~ [yY] ]]; then
        log_warn "РЈРґР°Р»РµРЅРёРµ РѕС‚РјРµРЅРµРЅРѕ."
        exit 0
    fi
}

remove_nginx_config() {
    if [[ -f "$NGINX_CONF" ]] || [[ -L "$NGINX_LINK" ]]; then
        log_info "РЈРґР°Р»РµРЅРёРµ РєРѕРЅС„РёРіСѓСЂР°С†РёРё Nginx..."
        run_with_spinner "РЈРґР°Р»РµРЅРёРµ СЃРёРјРІРѕР»РёС‡РµСЃРєРѕР№ СЃСЃС‹Р»РєРё" sudo rm -f "$NGINX_LINK" || true
        run_with_spinner "РЈРґР°Р»РµРЅРёРµ РєРѕРЅС„РёРіСѓСЂР°С†РёРё" sudo rm -f "$NGINX_CONF" || true
        
        if command -v nginx >/dev/null 2>&1; then
            run_with_spinner "РџСЂРѕРІРµСЂРєР° РєРѕРЅС„РёРіСѓСЂР°С†РёРё Nginx" sudo nginx -t || log_warn "РџСЂРѕРІРµСЂРєР° РєРѕРЅС„РёРіСѓСЂР°С†РёРё Р·Р°РІРµСЂС€РёР»Р°СЃСЊ СЃ РѕС€РёР±РєРѕР№"
            run_with_spinner "РџРµСЂРµР·Р°РіСЂСѓР·РєР° Nginx" sudo systemctl reload nginx || log_warn "РќРµ СѓРґР°Р»РѕСЃСЊ РїРµСЂРµР·Р°РіСЂСѓР·РёС‚СЊ Nginx"
        fi
        
        log_success "РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx СѓРґР°Р»РµРЅР°"
    else
        log_warn "РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx РЅРµ РЅР°Р№РґРµРЅР°"
    fi
}

remove_ssl_certs() {
    if [[ "$REMOVE_SSL" == "true" ]]; then
        local domain
        domain=$(get_domain_from_nginx || echo "")
        
        if [[ -z "$domain" ]]; then
            log_warn "РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РґРѕРјРµРЅ РёР· РєРѕРЅС„РёРіСѓСЂР°С†РёРё"
            return 1
        fi
        
        if [[ -d "/etc/letsencrypt/live/${domain}" ]]; then
            log_info "РЈРґР°Р»РµРЅРёРµ SSL СЃРµСЂС‚РёС„РёРєР°С‚РѕРІ РґР»СЏ $domain..."
            run_with_spinner "РЈРґР°Р»РµРЅРёРµ РґРёСЂРµРєС‚РѕСЂРёРё СЃРµСЂС‚РёС„РёРєР°С‚РѕРІ" sudo rm -rf "/etc/letsencrypt/live/${domain}" || true
            run_with_spinner "РЈРґР°Р»РµРЅРёРµ Р°СЂС…РёРІР° СЃРµСЂС‚РёС„РёРєР°С‚РѕРІ" sudo rm -rf "/etc/letsencrypt/archive/${domain}" || true
            run_with_spinner "РЈРґР°Р»РµРЅРёРµ renewal РєРѕРЅС„РёРіСѓСЂР°С†РёРё" sudo rm -f "/etc/letsencrypt/renewal/${domain}.conf" || true
            log_success "SSL СЃРµСЂС‚РёС„РёРєР°С‚С‹ СѓРґР°Р»РµРЅС‹"
        else
            log_warn "SSL СЃРµСЂС‚РёС„РёРєР°С‚С‹ РґР»СЏ $domain РЅРµ РЅР°Р№РґРµРЅС‹"
        fi
    fi
}

remove_docker_containers() {
    if [[ "$REMOVE_DOCKER" == "true" ]]; then
        if ! command -v docker >/dev/null 2>&1; then
            log_warn "Docker РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ"
            return 0
        fi
        
        log_info "РЈРґР°Р»РµРЅРёРµ Docker РєРѕРЅС‚РµР№РЅРµСЂРѕРІ..."
        
        # РџРµСЂРµС…РѕРґРёРј РІ РєР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° РµСЃР»Рё РѕРЅ СЃСѓС‰РµСЃС‚РІСѓРµС‚
        if [[ -d "$PROJECT_DIR" ]]; then
            cd "$PROJECT_DIR"
            
            if [[ -f "docker-compose.yml" ]]; then
                run_with_spinner "РћСЃС‚Р°РЅРѕРІРєР° Рё СѓРґР°Р»РµРЅРёРµ РєРѕРЅС‚РµР№РЅРµСЂРѕРІ (docker-compose)" \
                    sudo bash -c "docker-compose down --rmi all --remove-orphans 2>/dev/null" || true
            fi
            
            cd - > /dev/null
        fi
        
        # РЈРґР°Р»СЏРµРј РІСЃРµ РєРѕРЅС‚РµР№РЅРµСЂС‹ РѕС‚РЅРѕСЃСЏС‰РёРµСЃСЏ Рє РїСЂРѕРµРєС‚Сѓ
        local containers
        containers=$(docker ps -a --format "{{.Names}}" 2>/dev/null | grep "$PROJECT_DIR" || echo "")
        
        if [[ -n "$containers" ]]; then
            log_warn "РЈРґР°Р»РµРЅРёРµ РѕСЃС‚Р°РІС€РёС…СЃСЏ РєРѕРЅС‚РµР№РЅРµСЂРѕРІ..."
            echo "$containers" | while read -r container; do
                run_with_spinner "РЈРґР°Р»РµРЅРёРµ РєРѕРЅС‚РµР№РЅРµСЂР° $container" sudo docker rm -f "$container" || true
            done
        fi
        
        log_success "Docker РєРѕРЅС‚РµР№РЅРµСЂС‹ СѓРґР°Р»РµРЅС‹"
    fi
}

remove_project_directory() {
    if [[ "$REMOVE_PROJECT" == "true" ]]; then
        if [[ -d "$PROJECT_DIR" ]]; then
            log_info "РЈРґР°Р»РµРЅРёРµ РєР°С‚Р°Р»РѕРіР° РїСЂРѕРµРєС‚Р°..."
            run_with_spinner "РЈРґР°Р»РµРЅРёРµ $PROJECT_DIR" sudo rm -rf "$PROJECT_DIR" || true
            log_success "РљР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° СѓРґР°Р»С‘РЅ"
        else
            log_warn "РљР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° РЅРµ РЅР°Р№РґРµРЅ"
        fi
    fi
}

remove_certbot() {
    if [[ "$REMOVE_CERTBOT" == "true" ]]; then
        if ! command -v certbot >/dev/null 2>&1; then
            log_warn "Certbot РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ"
            return 0
        fi
        
        log_info "РЈРґР°Р»РµРЅРёРµ Certbot..."
        
        # РџСЂРѕРІРµСЂСЏРµРј РєР°Рє Р±С‹Р» СѓСЃС‚Р°РЅРѕРІР»РµРЅ Certbot
        if snap list 2>/dev/null | grep -q certbot; then
            log_warn "Certbot СѓСЃС‚Р°РЅРѕРІР»РµРЅ С‡РµСЂРµР· snap, СѓРґР°Р»РµРЅРёРµ..."
            run_with_spinner "РЈРґР°Р»РµРЅРёРµ Certbot (snap)" sudo snap remove certbot || true
        fi
        
        if dpkg -l 2>/dev/null | grep -q certbot; then
            log_warn "Certbot СѓСЃС‚Р°РЅРѕРІР»РµРЅ С‡РµСЂРµР· apt, СѓРґР°Р»РµРЅРёРµ..."
            run_with_spinner "РЈРґР°Р»РµРЅРёРµ python3-certbot-nginx" \
                sudo bash -c "export DEBIAN_FRONTEND=noninteractive && apt-get remove -y python3-certbot-nginx certbot 2>/dev/null" || true
        fi
        
        # РЈРґР°Р»СЏРµРј РґРёСЂРµРєС‚РѕСЂРёСЋ Let's Encrypt (РµСЃР»Рё РІС‹Р±СЂР°РЅ С„Р»Р°Рі)
        if [[ -d "/etc/letsencrypt" ]]; then
            log_input "РЈРґР°Р»РёС‚СЊ РІСЃРµ СЃРµСЂС‚РёС„РёРєР°С‚С‹ Let's Encrypt (/etc/letsencrypt)? (y/N): "
            read -r -n1 REPLY < /dev/tty || true
            echo ""
            if [[ "$REPLY" =~ [yY] ]]; then
                run_with_spinner "РЈРґР°Р»РµРЅРёРµ /etc/letsencrypt" sudo rm -rf /etc/letsencrypt || true
                log_warn "Р’СЃРµ СЃРµСЂС‚РёС„РёРєР°С‚С‹ Let's Encrypt СѓРґР°Р»РµРЅС‹"
            fi
        fi
        
        log_success "Certbot СѓРґР°Р»С‘РЅ"
    fi
}

# --- РќР°С‡Р°Р»Рѕ РІС‹РїРѕР»РЅРµРЅРёСЏ ---

show_header
ensure_sudo_refresh

# РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ СЌС‚Рѕ РЅРµ РіР»Р°РІРЅС‹Р№ РєР°С‚Р°Р»РѕРі
if [[ "$PWD" == "/" ]] || [[ "$PWD" == "/root" ]] || [[ "$PWD" == "$HOME" ]]; then
    log_warn "РќРµ СЂРµРєРѕРјРµРЅРґСѓРµС‚СЃСЏ Р·Р°РїСѓСЃРєР°С‚СЊ СЃРєСЂРёРїС‚ РёР· РєРѕСЂРЅРµРІРѕРіРѕ РёР»Рё РґРѕРјР°С€РЅРµРіРѕ РєР°С‚Р°Р»РѕРіР°"
fi

# РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё С‡С‚Рѕ СѓРґР°Р»СЏС‚СЊ
if ! [[ -f "$NGINX_CONF" ]] && ! [[ -L "$NGINX_LINK" ]] && ! [[ -d "$PROJECT_DIR" ]]; then
    log_error "Remnawave Shopbot РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ. РќРµС‡РµРіРѕ СѓРґР°Р»СЏС‚СЊ."
    exit 1
fi

log_info "РћР±РЅР°СЂСѓР¶РµРЅР° СЃСѓС‰РµСЃС‚РІСѓСЋС‰Р°СЏ СѓСЃС‚Р°РЅРѕРІРєР° Remnawave Shopbot"
echo ""

# РџРѕРєР°Р·С‹РІР°РµРј РјРµРЅСЋ
show_menu

# РџРѕРєР°Р·С‹РІР°РµРј РёС‚РѕРіРѕРІС‹Р№ СЃРїРёСЃРѕРє
show_removal_summary

echo ""
echo -e "${RED}${BOLD}в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ${NC}"
echo -e "${RED}${BOLD}               РќРђР§РРќРђР•РўРЎРЇ РЈР”РђР›Р•РќРР•...                           ${NC}"
echo -e "${RED}${BOLD}в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ${NC}"
echo ""

# Р’С‹РїРѕР»РЅСЏРµРј СѓРґР°Р»РµРЅРёРµ
[[ "$REMOVE_CONFIG" == "true" ]] && remove_nginx_config
[[ "$REMOVE_SSL" == "true" ]] && remove_ssl_certs
[[ "$REMOVE_DOCKER" == "true" ]] && remove_docker_containers
[[ "$REMOVE_PROJECT" == "true" ]] && remove_project_directory
[[ "$REMOVE_CERTBOT" == "true" ]] && remove_certbot

echo ""
echo -e "${GREEN}в”Џв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”“${NC}"
echo -e "${GREEN}в”ѓ                  РЈР”РђР›Р•РќРР• Р—РђР’Р•Р РЁР•РќРћ!                          в”ѓ${NC}"
echo -e "${GREEN}в”—в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”›${NC}"
echo ""

# РџРѕРєР°Р·С‹РІР°РµРј РѕСЃС‚Р°РІС€РёРµСЃСЏ С„Р°Р№Р»С‹/СЃРµСЂРІРёСЃС‹
if [[ -f "$NGINX_CONF" ]] || [[ -L "$NGINX_LINK" ]]; then
    log_warn "РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx РІСЃС‘ РµС‰С‘ СЃСѓС‰РµСЃС‚РІСѓРµС‚:"
    [[ -f "$NGINX_CONF" ]] && echo -e "  ${CYAN}$NGINX_CONF${NC}"
    [[ -L "$NGINX_LINK" ]] && echo -e "  ${CYAN}$NGINX_LINK${NC}"
fi

if [[ -d "$PROJECT_DIR" ]]; then
    log_warn "РљР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° РІСЃС‘ РµС‰С‘ СЃСѓС‰РµСЃС‚РІСѓРµС‚: ${CYAN}$PROJECT_DIR${NC}"
fi

if command -v docker >/dev/null 2>&1 && docker ps -a 2>/dev/null | grep -q "$PROJECT_DIR"; then
    log_warn "Docker РєРѕРЅС‚РµР№РЅРµСЂС‹ РїСЂРѕРµРєС‚Р° РІСЃС‘ РµС‰С‘ СЃСѓС‰РµСЃС‚РІСѓСЋС‚"
fi

# РќР°РїРѕРјРёРЅР°РµРј РїСЂРѕ СЃРѕС…СЂР°РЅС‘РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ РЅРѕРІРѕРіРѕ РґРѕРјРµРЅР°
if [[ -n "$local_db_backup" && -f "$local_db_backup" ]]; then
    log_info "РљРѕРїРёСЏ Р‘Р” СЃРѕС…СЂР°РЅРµРЅР°: ${CYAN}${local_db_backup}${NC}"
    log_info "Р’РѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёРµ: РїРѕР»РѕР¶РёС‚Рµ С„Р°Р№Р» РєР°Рє users.db РІ РєР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° Рё Р·Р°РїСѓСЃС‚РёС‚Рµ"
    log_info "РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёРµ С‡РµСЂРµР· Р°РґРјРёРЅРєСѓ (restore РїСЂРѕРІРµСЂРёС‚ schema version Рё snapshots)."
fi
if [[ -d "$HOME/shopbot-backups" ]]; then
    log_info "РђСЂС…РёРІС‹ Р±СЌРєР°РїРѕРІ СЃРѕС…СЂР°РЅРµРЅС‹: ${CYAN}$HOME/shopbot-backups${NC}"
fi

echo ""
log_info "Р”Р»СЏ РїРѕР»РЅРѕРіРѕ СѓРґР°Р»РµРЅРёСЏ РѕСЃС‚Р°С‚РєРѕРІ РІС‹РїРѕР»РЅРёС‚Рµ РІСЂСѓС‡РЅСѓСЋ:"
echo -e "  ${CYAN}sudo rm -rf $PROJECT_DIR${NC}"
echo -e "  ${CYAN}sudo rm -f $NGINX_LINK $NGINX_CONF${NC}"
echo -e "  ${CYAN}docker volume rm shopbot-backups${NC}  (РµСЃР»Рё Р±СЌРєР°РїС‹ Р±РѕР»СЊС€Рµ РЅРµ РЅСѓР¶РЅС‹)"
echo ""

show_footer
