#!/usr/bin/env bash
set -Eeuo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

REPO_URL="https://github.com/CyberERROR/remnawave-shopbot.git"
PROJECT_NAME="remnawave-shopbot"

# === РРЎРџР РђР’Р›Р•РќРР• РџРЈРўР === 
PROJECT_DIR="$HOME/$PROJECT_NAME"
    
# РќР° РІСЃСЏРєРёР№ СЃР»СѓС‡Р°Р№ РїСЂРѕРІРµСЂСЏРµРј С‚РµРєСѓС‰СѓСЋ РїР°РїРєСѓ, РµСЃР»Рё РІРґСЂСѓРі СѓСЃС‚Р°РЅРѕРІРёР»Рё РІ РЅРµСЃС‚Р°РЅРґР°СЂС‚РЅРѕРµ РјРµСЃС‚Рѕ
if [[ ! -d "$PROJECT_DIR" ]] && [[ -d "./$PROJECT_NAME" ]]; then
    PROJECT_DIR="$(pwd)/$PROJECT_NAME"
fi

NGINX_CONF="/etc/nginx/sites-available/${PROJECT_NAME}.conf"
NGINX_LINK="/etc/nginx/sites-enabled/${PROJECT_NAME}.conf"

USER_DOMAIN_INPUT=""
DOMAIN=""
EMAIL=""
YOOKASSA_PORT=""

show_header() {
    clear
    echo -e "${PURPLE}${BOLD}в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ${NC}"
    echo -e "${PURPLE}${BOLD}           REMNAWAVE SHOPBOT INSTALLER & UPDATER              ${NC}"
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

run_with_spinner() {
    local message="$1"
    shift
    local cmd=("$@")

    echo -ne "${BLUE}${BOLD}[вћњ]${NC} ${message}... "

    local temp_log
    temp_log=$(mktemp)
    
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

run_with_animated_spinner() {
    local message="$1"
    shift
    local cmd=("$@")

    echo -ne "${BLUE}${BOLD}[вћњ]${NC} ${message}... "

    local temp_log
    temp_log=$(mktemp)
    
    "${cmd[@]}" > "$temp_log" 2>&1 &
    local pid=$!
    
    local delay=0.1
    local spinstr='|/-\'
    
    tput civis 2>/dev/null || true

    while ps -p "$pid" > /dev/null 2>&1; do
        local temp=${spinstr#?}
        printf "[%c]" "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b"
    done

    wait "$pid"
    local exit_code=$?

    tput cnorm 2>/dev/null || true
    printf "   \b\b\b"

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}${BOLD}OK${NC}"
        rm -f "$temp_log"
        return 0
    else
        echo -e "${RED}${BOLD}FAILED${NC}"
        echo -e "\n${RED}================ LOG OUTPUT =================${NC}"
        cat "$temp_log"
        echo -e "${RED}=============================================${NC}"
        rm -f "$temp_log"
        return $exit_code
    fi
}

on_error() {
    tput cnorm 2>/dev/null || true
    echo ""
    log_error "РЎРєСЂРёРїС‚ РїСЂРµСЂРІР°РЅ РЅР° СЃС‚СЂРѕРєРµ $1."
    exit 1
}
trap 'on_error $LINENO' ERR

sanitize_domain() {
    if [[ -z "${1:-}" ]]; then
        echo ""
        return 0
    fi
    echo "$1" | sed -e 's%^https\?://%%' -e 's%/.*$%%' | tr -cd 'A-Za-z0-9.-' | tr '[:upper:]' '[:lower:]'
}

get_server_ip() {
    local ipv4_re='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
    local ip
    for url in "https://api.ipify.org" "https://ifconfig.co/ip" "https://ipv4.icanhazip.com"; do
        ip=$(curl -fsS --max-time 3 "$url" 2>/dev/null | tr -d '\r\n\t ') || true
        if [[ $ip =~ $ipv4_re ]]; then
            echo "$ip"
            return 0
        fi
    done
    ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    if [[ $ip =~ $ipv4_re ]]; then echo "$ip"; fi
}

resolve_domain_ip() {
    local domain="${1:-}"
    [[ -z "$domain" ]] && return 1
    
    local ipv4_re='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
    local ip
    
    ip=$(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | head -n1)
    if [[ $ip =~ $ipv4_re ]]; then echo "$ip"; return 0; fi
    
    if command -v dig >/dev/null 2>&1; then
        ip=$(dig +short A "$domain" 2>/dev/null | grep -E "$ipv4_re" | head -n1)
        if [[ $ip =~ $ipv4_re ]]; then echo "$ip"; return 0; fi
    fi
    return 1
}

get_domain_from_nginx() {
    if [[ -f "$NGINX_CONF" ]]; then
        grep "server_name" "$NGINX_CONF" | awk '{print $2}' | sed 's/;//' | head -n1
    fi
}

get_port_from_nginx() {
    if [[ -f "$NGINX_CONF" ]]; then
        grep "listen" "$NGINX_CONF" | head -n1 | awk '{print $2}' | sed 's/;//'
    fi
}

ensure_sudo_refresh() {
    if ! sudo -v; then
        log_error "РўСЂРµР±СѓСЋС‚СЃСЏ РїСЂР°РІР° sudo. Р’РІРµРґРёС‚Рµ РїР°СЂРѕР»СЊ РІС‹С€Рµ."
        exit 1
    fi
}

ensure_packages() {
    declare -A packages=( 
        [git]='git' 
        [docker]='docker.io' 
        [docker-compose]='docker-compose' 
        [nginx]='nginx' 
        [curl]='curl' 
        [certbot]='certbot' 
        [dig]='dnsutils' 
    )
    local missing=()
    local missing_desc=()
    
    for cmd in "${!packages[@]}"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing+=("${packages[$cmd]}")
            missing_desc+=("$cmd")
        fi
    done

    if ((${#missing[@]})); then
        echo -e "${BLUE}${BOLD}[вћњ]${NC} РўСЂРµР±СѓСЋС‚СЃСЏ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё: ${CYAN}${missing_desc[*]}${NC}"
        run_with_animated_spinner "РЈСЃС‚Р°РЅРѕРІРєР° Р·Р°РІРёСЃРёРјРѕСЃС‚РµР№ (${missing[*]})" \
            sudo bash -c "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y --no-install-recommends ${missing[*]}" || {
            log_error "РќРµ СѓРґР°Р»РѕСЃСЊ СѓСЃС‚Р°РЅРѕРІРёС‚СЊ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё"
            exit 1
        }
    else
        log_success "РЎРёСЃС‚РµРјРЅС‹Рµ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РІ РїРѕСЂСЏРґРєРµ"
    fi
}

ensure_services() {
    run_with_spinner "РџСЂРѕРІРµСЂРєР° Docker" sudo systemctl enable docker || true
    run_with_spinner "Р—Р°РїСѓСЃРє Docker" sudo systemctl start docker || true
    run_with_spinner "РџСЂРѕРІРµСЂРєР° Nginx" sudo systemctl enable nginx || true
    run_with_spinner "Р—Р°РїСѓСЃРє Nginx" sudo systemctl start nginx || true
}

ensure_certbot_nginx() {
    if command -v certbot >/dev/null 2>&1 && certbot plugins 2>/dev/null | grep -qi 'nginx'; then
        log_success "РџР»Р°РіРёРЅ Certbot Nginx Р°РєС‚РёРІРµРЅ"
        return 0
    fi

    log_info "РЈСЃС‚Р°РЅРѕРІРєР° РїР»Р°РіРёРЅР° Certbot РґР»СЏ Nginx..."
    
    run_with_animated_spinner "РЈСЃС‚Р°РЅРѕРІРєР° python3-certbot-nginx" \
        sudo bash -c "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y --no-install-recommends python3-certbot-nginx" || {
        log_warn "РџРѕРїС‹С‚РєР° СѓСЃС‚Р°РЅРѕРІРєРё С‡РµСЂРµР· snap..."
        
        if ! command -v snap >/dev/null 2>&1; then
            run_with_animated_spinner "РЈСЃС‚Р°РЅРѕРІРєР° snapd" \
                sudo bash -c "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y --no-install-recommends snapd" || {
                log_error "РќРµ СѓРґР°Р»РѕСЃСЊ СѓСЃС‚Р°РЅРѕРІРёС‚СЊ snapd"
                exit 1
            }
        fi
        
        run_with_animated_spinner "РЈСЃС‚Р°РЅРѕРІРєР° Certbot С‡РµСЂРµР· snap" \
            sudo bash -c "snap install core 2>/dev/null; snap refresh core 2>/dev/null; snap install --classic certbot 2>/dev/null; ln -sf /snap/bin/certbot /usr/bin/certbot" || {
            log_error "РќРµ СѓРґР°Р»РѕСЃСЊ СѓСЃС‚Р°РЅРѕРІРёС‚СЊ Certbot"
            exit 1
        }
    }
    
    if certbot plugins 2>/dev/null | grep -qi 'nginx'; then
        log_success "РџР»Р°РіРёРЅ Certbot Nginx СѓСЃРїРµС€РЅРѕ РЅР°СЃС‚СЂРѕРµРЅ"
    else
        log_error "РќРµ СѓРґР°Р»РѕСЃСЊ СѓСЃС‚Р°РЅРѕРІРёС‚СЊ РїР»Р°РіРёРЅ Nginx РґР»СЏ Certbot"
        exit 1
    fi
}

configure_nginx() {
    local domain="$1"
    local port="$2"
    
    log_info "РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx РґР»СЏ $domain:$port"
    
    sudo tee "$NGINX_CONF" >/dev/null <<EOF
server {
    listen ${port} ssl http2;
    listen [::]:${port} ssl http2;
    server_name ${domain};
    client_max_body_size 500M;

    ssl_certificate /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        proxy_pass http://127.0.0.1:1488;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    
    if [[ ! -L "$NGINX_LINK" ]]; then
        sudo ln -s "$NGINX_CONF" "$NGINX_LINK" 2>/dev/null || true
    fi

    run_with_spinner "РџСЂРѕРІРµСЂРєР° РєРѕРЅС„РёРіСѓСЂР°С†РёРё Nginx" sudo nginx -t || {
        log_error "РќРµРєРѕСЂСЂРµРєС‚РЅР°СЏ РєРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx"
        exit 1
    }
    
    run_with_spinner "РџРµСЂРµР·Р°РіСЂСѓР·РєР° Nginx" sudo systemctl reload nginx || {
        log_error "РќРµ СѓРґР°Р»РѕСЃСЊ РїРµСЂРµР·Р°РіСЂСѓР·РёС‚СЊ Nginx"
        exit 1
    }
}

show_docker_images() {
    if command -v docker >/dev/null 2>&1 && [[ -f "docker-compose.yml" ]]; then
        echo -e "${BLUE}${BOLD}[INFO]${NC} Docker РєРѕРЅС‚РµР№РЅРµСЂС‹ РІ РїСЂРѕРµРєС‚Рµ:"
        docker-compose config --services 2>/dev/null | sed 's/^/  - /' || true
    fi
}

show_header
ensure_sudo_refresh

if [[ -f "$NGINX_CONF" ]]; then
    
    # 1. РџСЂРѕРІРµСЂСЏРµРј, СЃСѓС‰РµСЃС‚РІСѓРµС‚ Р»Рё РїР°РїРєР° РїРѕ РѕР¶РёРґР°РµРјРѕРјСѓ РїСѓС‚Рё
    if [[ ! -d "$PROJECT_DIR" ]]; then
        log_warn "РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Nginx РЅР°Р№РґРµРЅР°, РЅРѕ РїР°РїРєР° СЃ Р±РѕС‚РѕРј РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ РїРѕ РїСѓС‚Рё: $PROJECT_DIR"
        
        # 2. РџРѕРїС‹С‚РєР° Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРіРѕ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ (РєР»РѕРЅ)
        log_info "Р—Р°РїСѓСЃРє Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРіРѕ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ С„Р°Р№Р»РѕРІ..."
        ensure_packages
        
        run_with_animated_spinner "Р’РѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёРµ СЂРµРїРѕР·РёС‚РѕСЂРёСЏ" git clone "$REPO_URL" "$PROJECT_DIR" || {
            log_error "РљСЂРёС‚РёС‡РµСЃРєР°СЏ РѕС€РёР±РєР°: РЅРµ СѓРґР°Р»РѕСЃСЊ РєР»РѕРЅРёСЂРѕРІР°С‚СЊ СЂРµРїРѕР·РёС‚РѕСЂРёР№ РІ $PROJECT_DIR."
            exit 1
        }
    fi
    
    # 3. РўРµРїРµСЂСЊ РїР°РїРєР° РґРѕР»Р¶РЅР° СЃСѓС‰РµСЃС‚РІРѕРІР°С‚СЊ
    if [[ -d "$PROJECT_DIR" ]]; then
        log_info "Р РµР¶РёРј РѕР±РЅРѕРІР»РµРЅРёСЏ Р°РєС‚РёРІРµРЅ. РџСѓС‚СЊ: $PROJECT_DIR"
        
        cd "$PROJECT_DIR"
        
        DOMAIN=$(get_domain_from_nginx)
        YOOKASSA_PORT=$(get_port_from_nginx)
        
        if [[ -z "$DOMAIN" ]]; then
            log_error "РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕС‡РёС‚Р°С‚СЊ РґРѕРјРµРЅ РёР· РєРѕРЅС„РёРіСѓСЂР°С†РёРё Nginx. Р’РѕР·РјРѕР¶РЅРѕ, С„Р°Р№Р» РїРѕРІСЂРµР¶РґРµРЅ."
            exit 1
        fi
        
        run_with_animated_spinner "РћР±РЅРѕРІР»РµРЅРёРµ С„Р°Р№Р»РѕРІ (Hard Reset)" \
            bash -c "git fetch origin main && git reset --hard origin/main" || {
            log_error "РќРµ СѓРґР°Р»РѕСЃСЊ РѕР±РЅРѕРІРёС‚СЊ СЂРµРїРѕР·РёС‚РѕСЂРёР№"
            exit 1
        }
        
        echo ""
        show_docker_images
        echo ""
        
        # Р‘СЌРєР°Рї Р‘Р” РїРµСЂРµРґ РѕР±РЅРѕРІР»РµРЅРёРµРј: РјРёРіСЂР°С†РёСЏ СЃС…РµРјС‹ (schema_version=2, РіРёР±СЂРёРґ/РґРѕРєСѓРїРєР°/fulfillment)
        if [[ -f "$PROJECT_DIR/users.db" ]]; then
            local_backup="users-before-update-$(date +%Y%m%d-%H%M%S).db"
            run_with_spinner "Р РµР·РµСЂРІРЅР°СЏ РєРѕРїРёСЏ Р‘Р” РїРµСЂРµРґ РѕР±РЅРѕРІР»РµРЅРёРµРј (${local_backup})" \
                cp "$PROJECT_DIR/users.db" "$PROJECT_DIR/${local_backup}" || {
                log_error "РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ СЂРµР·РµСЂРІРЅСѓСЋ РєРѕРїРёСЋ Р‘Р”. РћР±РЅРѕРІР»РµРЅРёРµ РїСЂРµСЂРІР°РЅРѕ (Р·Р°С‰РёС‚Р° РґР°РЅРЅС‹С…)."
                exit 1
            }
            # С…СЂР°РЅРёРј РЅРµ Р±РѕР»РµРµ 3 pre-update РєРѕРїРёР№
            ls -1t "$PROJECT_DIR"/users-before-update-*.db 2>/dev/null | tail -n +4 | while read -r old; do
                rm -f "$old"
            done || true
        else
            log_warn "users.db РЅРµ РЅР°Р№РґРµРЅ вЂ” РїСЂРѕРїСѓСЃРєР°СЋ Р±СЌРєР°Рї (РїРµСЂРІС‹Р№ Р·Р°РїСѓСЃРє?)"
        fi
        
        ensure_services
        
        run_with_animated_spinner "РџРµСЂРµСЃР±РѕСЂРєР° РєРѕРЅС‚РµР№РЅРµСЂРѕРІ" \
            sudo bash -c "docker-compose down --remove-orphans && docker-compose up -d --build" || {
            log_error "РќРµ СѓРґР°Р»РѕСЃСЊ РїРµСЂРµСЃРѕР±СЂР°С‚СЊ РєРѕРЅС‚РµР№РЅРµСЂС‹"
            exit 1
        }
        
        # РњРёРіСЂР°С†РёСЏ Р‘Р” РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РїСЂРё СЃС‚Р°СЂС‚Рµ (initialize_db/run_migration).
        # Р“Р°СЂР°РЅС‚РёСЂСѓРµРј РїСЂРѕРіРѕРЅ СЏРІРЅС‹Рј РІС‹Р·РѕРІРѕРј, С‡С‚РѕР±С‹ РѕС€РёР±РєРё СЃС…РµРјС‹ Р±С‹Р»Рё РІРёРґРЅС‹ РІ Р»РѕРіРµ СѓСЃС‚Р°РЅРѕРІРєРё.
        run_with_spinner "РњРёРіСЂР°С†РёСЏ Р‘Р” (run_migration)" \
            sudo bash -c "docker-compose run --rm --no-deps --entrypoint '' remnawave-shopbot /app/.venv/bin/python -c 'from shop_bot.data_manager.database import initialize_db; initialize_db()'" || {
            log_warn "РњРёРіСЂР°С†РёСЏ Р·Р°РІРµСЂС€РёР»Р°СЃСЊ СЃ РѕС€РёР±РєРѕР№ вЂ” РїСЂРѕРІРµСЂСЊС‚Рµ Р»РѕРіРё РєРѕРЅС‚РµР№РЅРµСЂР°. РћР±РЅРѕРІР»С‘РЅРЅР°СЏ Р‘Р” РІРѕСЃСЃС‚Р°РЅРѕРІРёРјР° РёР· ${local_backup:-Р±СЌРєР°РїР°}."
        }
        
        # Р®РЅРёС‚-С‚РµСЃС‚С‹ РЅРѕРІРѕРіРѕ РґРѕРјРµРЅР° (Р­С‚Р°Рї 0 РўР—)
        run_with_spinner "РўРµСЃС‚С‹ РЅРѕРІРѕРіРѕ РґРѕРјРµРЅР° (pytest)" \
            sudo bash -c "docker-compose run --rm --no-deps --entrypoint '' remnawave-shopbot /app/.venv/bin/python -m pytest tests/ -q" || {
            log_warn "Р§Р°СЃС‚СЊ С‚РµСЃС‚РѕРІ РЅРµ РїСЂРѕС€Р»Р° вЂ” РїСЂРѕРІРµСЂСЊС‚Рµ РІС‹РІРѕРґ РІС‹С€Рµ РїРµСЂРµРґ СЂРµР»РёР·РѕРј."
        }
        
        echo ""
        echo -e "${GREEN}в”Џв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”“${NC}"
        echo -e "${GREEN}в”ѓ           РћР‘РќРћР’Р›Р•РќРР• / Р’РћРЎРЎРўРђРќРћР’Р›Р•РќРР• Р—РђР’Р•Р РЁР•РќРћ!             в”ѓ${NC}"
        echo -e "${GREEN}в”—в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”›${NC}"
        echo ""
        echo -e " ${BOLD}РђРґСЂРµСЃ РїР°РЅРµР»Рё:${NC}     https://${DOMAIN}:${YOOKASSA_PORT}/login"
        echo -e " ${BOLD}Р”Р°РЅРЅС‹Рµ РІС…РѕРґР°:${NC}     ${CYAN}admin${NC} / ${CYAN}admin${NC}"
        echo -e " ${BOLD}Webhook URL:${NC}      https://${DOMAIN}:${YOOKASSA_PORT}/yookassa-webhook"
        echo ""
        echo -e " ${BOLD}РќРѕРІРѕРµ РІ СЌС‚РѕР№ РІРµСЂСЃРёРё:${NC}"
        echo -e "   вЂў Р“РёР±СЂРёРґРЅС‹Рµ РїРѕРґРїРёСЃРєРё Рё РґРѕРєСѓРїРєР° С‚СЂР°С„РёРєР° вЂ” РІРєР»СЋС‡Р°СЋС‚СЃСЏ per-host РІ Р°РґРјРёРЅРєРµ"
        echo -e "     (РќР°СЃС‚СЂРѕР№РєРё в†’ С…РѕСЃС‚ в†’ В«Р“РёР±СЂРёРґ Рё РґРѕРєСѓРїРєР° С‚СЂР°С„РёРєР°'); РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РІС‹РєР»СЋС‡РµРЅС‹."
        echo -e "   вЂў РќР°РґС‘Р¶РЅР°СЏ РѕР±СЂР°Р±РѕС‚РєР° РѕРїР»Р°С‚: fulfillment-РѕС‡РµСЂРµРґСЊ СЃ retry Рё manual review."
        echo -e "   вЂў Р‘СЌРєР°РїС‹ С‚РµРїРµСЂСЊ СЃРѕРґРµСЂР¶Р°С‚ СЃРЅРёРјРєРё СЃРѕСЃС‚РѕСЏРЅРёСЏ Remnawave (snapshot)."
        echo ""
        show_footer
        exit 0
    fi
fi

log_info "РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ РїСЂРѕС†РµСЃСЃР° С‡РёСЃС‚РѕР№ СѓСЃС‚Р°РЅРѕРІРєРё..."
echo ""

ensure_packages
ensure_services
ensure_certbot_nginx

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    run_with_animated_spinner "РљР»РѕРЅРёСЂРѕРІР°РЅРёРµ СЂРµРїРѕР·РёС‚РѕСЂРёСЏ" git clone "$REPO_URL" "$PROJECT_DIR" || {
        log_error "РќРµ СѓРґР°Р»РѕСЃСЊ РєР»РѕРЅРёСЂРѕРІР°С‚СЊ СЂРµРїРѕР·РёС‚РѕСЂРёР№"
        exit 1
    }
else
    log_warn "РљР°С‚Р°Р»РѕРі РїСЂРѕРµРєС‚Р° СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓРµС‚ ($PROJECT_DIR), РїСЂРѕРїСѓСЃРєР°РµРј РєР»РѕРЅРёСЂРѕРІР°РЅРёРµ"
fi
cd "$PROJECT_DIR"

echo ""

DOMAIN=""
while [[ -z "$DOMAIN" ]]; do
    log_input "Р’РІРµРґРёС‚Рµ РІР°С€ РґРѕРјРµРЅ (Р±РµР· http/s): "
    read -r USER_DOMAIN_INPUT < /dev/tty || true
    
    if [[ -z "$USER_DOMAIN_INPUT" ]]; then
        log_warn "Р”РѕРјРµРЅ РЅРµ РјРѕР¶РµС‚ Р±С‹С‚СЊ РїСѓСЃС‚С‹Рј."
        continue
    fi
    
    DOMAIN=$(sanitize_domain "$USER_DOMAIN_INPUT")
    if [[ -z "$DOMAIN" ]]; then
        log_warn "Р”РѕРјРµРЅ СЃРѕРґРµСЂР¶РёС‚ РЅРµРґРѕРїСѓСЃС‚РёРјС‹Рµ СЃРёРјРІРѕР»С‹."
        DOMAIN=""
    fi
done

EMAIL=""
while [[ -z "$EMAIL" ]]; do
    log_input "Р’РІРµРґРёС‚Рµ Email РґР»СЏ SSL (Let's Encrypt): "
    read -r EMAIL < /dev/tty || true
    
    if [[ -z "$EMAIL" ]]; then
        log_warn "Email РЅРµ РјРѕР¶РµС‚ Р±С‹С‚СЊ РїСѓСЃС‚С‹Рј."
    fi
done

echo ""

SERVER_IP=$(get_server_ip || true)
DOMAIN_IP=$(resolve_domain_ip "$DOMAIN" || true)

if [[ -n "$SERVER_IP" ]]; then
    log_success "IP СЃРµСЂРІРµСЂР°: $SERVER_IP"
fi

if [[ -n "$DOMAIN_IP" ]]; then
    log_success "IP РґРѕРјРµРЅР°: $DOMAIN_IP"
fi

if [[ -n "$SERVER_IP" ]] && [[ -n "$DOMAIN_IP" ]] && [[ "$SERVER_IP" != "$DOMAIN_IP" ]]; then
    log_warn "Р’РЅРёРјР°РЅРёРµ: IP СЃРµСЂРІРµСЂР° ($SERVER_IP) РѕС‚Р»РёС‡Р°РµС‚СЃСЏ РѕС‚ IP РґРѕРјРµРЅР° ($DOMAIN_IP)."
    log_warn "Р­С‚Рѕ РјРѕР¶РµС‚ РїСЂРёРІРµСЃС‚Рё Рє РѕС€РёР±РєРµ РІС‹РґР°С‡Рё SSL СЃРµСЂС‚РёС„РёРєР°С‚Р°."
    
    REPLY=""
    while true; do
        log_input "РџСЂРѕРґРѕР»Р¶РёС‚СЊ РІСЃС‘ СЂР°РІРЅРѕ? (y/n): "
        read -r -n1 REPLY < /dev/tty || true
        echo ""
        case "$REPLY" in
            [yY]) break ;;
            [nN]) log_error "РЈСЃС‚Р°РЅРѕРІРєР° РѕС‚РјРµРЅРµРЅР°."; exit 1 ;;
            *) ;;
        esac
    done
fi

echo ""

if [[ -d "/etc/letsencrypt/live/${DOMAIN}" ]]; then
    log_success "SSL СЃРµСЂС‚РёС„РёРєР°С‚С‹ СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓСЋС‚ РґР»СЏ $DOMAIN"
else
    log_info "Р’С‹РїСѓСЃРє SSL СЃРµСЂС‚РёС„РёРєР°С‚Р° РѕС‚ Let's Encrypt РґР»СЏ $DOMAIN..."
    
    run_with_animated_spinner "РџРѕР»СѓС‡РµРЅРёРµ СЃРµСЂС‚РёС„РёРєР°С‚Р° (РјРѕР¶РµС‚ Р·Р°РЅСЏС‚СЊ РІСЂРµРјСЏ)" \
        sudo bash -c "certbot --nginx -d $DOMAIN --email $EMAIL --agree-tos --non-interactive --redirect --no-eff-email 2>&1" || {
        log_error "РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ SSL СЃРµСЂС‚РёС„РёРєР°С‚. РџСЂРѕРІРµСЂСЊС‚Рµ:"
        log_error "  - Р”РѕРјРµРЅ РїСЂР°РІРёР»СЊРЅРѕ СѓРєР°Р·Р°РЅ"
        log_error "  - Р”РѕРјРµРЅ СѓРєР°Р·С‹РІР°РµС‚ РЅР° СЌС‚РѕС‚ СЃРµСЂРІРµСЂ ($SERVER_IP)"
        log_error "  - РџРѕСЂС‚С‹ 80 Рё 443 РѕС‚РєСЂС‹С‚С‹"
        log_error "  - Email РїСЂР°РІРёР»СЊРЅС‹Р№"
        exit 1
    }
fi

echo ""
log_input "РџРѕСЂС‚ РґР»СЏ РІРµР±С…СѓРєРѕРІ YooKassa [1-65535] (default: 8443): "
read -r YOOKASSA_PORT_INPUT < /dev/tty || true
YOOKASSA_PORT="${YOOKASSA_PORT_INPUT:-8443}"

if ! [[ "$YOOKASSA_PORT" =~ ^[0-9]+$ ]] || (( YOOKASSA_PORT < 1 || YOOKASSA_PORT > 65535 )); then
    log_error "РџРѕСЂС‚ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ С†РµР»С‹Рј С‡РёСЃР»РѕРј РѕС‚ 1 РґРѕ 65535."
    exit 1
fi

if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q 'Status: active'; then
    run_with_spinner "РћС‚РєСЂС‹С‚РёРµ РїРѕСЂС‚РѕРІ UFW (80, 443, 1488, ${YOOKASSA_PORT})" \
        sudo bash -c "ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 1488/tcp && ufw allow ${YOOKASSA_PORT}/tcp" || {
        log_warn "РќРµ СѓРґР°Р»РѕСЃСЊ РЅР°СЃС‚СЂРѕРёС‚СЊ UFW"
    }
fi

echo ""
configure_nginx "$DOMAIN" "$YOOKASSA_PORT"

echo ""
show_docker_images
echo ""

run_with_animated_spinner "РЎР±РѕСЂРєР° Рё Р·Р°РїСѓСЃРє Docker РєРѕРЅС‚РµР№РЅРµСЂРѕРІ" \
    sudo bash -c "if [ -n \"\$(docker-compose ps -q 2>/dev/null)\" ]; then docker-compose down --remove-orphans; fi; docker-compose up -d --build" || {
    log_error "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ Docker РєРѕРЅС‚РµР№РЅРµСЂС‹"
    exit 1
}

# РњРёРіСЂР°С†РёСЏ Р‘Р” РЅРѕРІРѕРіРѕ РґРѕРјРµРЅР° (schema_version=2): РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ РїСЂРё СЃС‚Р°СЂС‚Рµ,
# РЅРѕ РїСЂРѕРіРѕРЅСЏРµРј СЏРІРЅРѕ, С‡С‚РѕР±С‹ РѕС€РёР±РєРё Р±С‹Р»Рё РІРёРґРЅС‹ СЃСЂР°Р·Сѓ
run_with_spinner "РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ Рё РјРёРіСЂР°С†РёСЏ Р‘Р” (initialize_db)" \
    sudo bash -c "docker-compose run --rm --no-deps --entrypoint '' remnawave-shopbot /app/.venv/bin/python -c 'from shop_bot.data_manager.database import initialize_db; initialize_db()'" || {
    log_warn "РњРёРіСЂР°С†РёСЏ Р·Р°РІРµСЂС€РёР»Р°СЃСЊ СЃ РѕС€РёР±РєРѕР№ вЂ” РїСЂРѕРІРµСЂСЊС‚Рµ: docker-compose logs remnawave-shopbot"
}

echo ""
echo -e "${GREEN}в”Џв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”“${NC}"
echo -e "${GREEN}в”ѓ                  РЈРЎРўРђРќРћР’РљРђ Р—РђР’Р•Р РЁР•РќРђ!                        в”ѓ${NC}"
echo -e "${GREEN}в”—в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”›${NC}"
echo ""
echo -e " ${BOLD}РђРґСЂРµСЃ РїР°РЅРµР»Рё:${NC}     https://${DOMAIN}:${YOOKASSA_PORT}/login"
echo -e " ${BOLD}Р”Р°РЅРЅС‹Рµ РІС…РѕРґР°:${NC}     ${CYAN}admin${NC} / ${CYAN}admin${NC}"
echo -e " ${BOLD}Webhook URL:${NC}      https://${DOMAIN}:${YOOKASSA_PORT}/yookassa-webhook"
echo ""
echo -e " ${BOLD}Webhook endpoints (РµРґРёРЅС‹Р№ РїРѕС‚РѕРє РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ):${NC}"
echo -e "   YooKassa:  https://${DOMAIN}:${YOOKASSA_PORT}/yookassa-webhook"
echo -e "   CryptoBot: https://${DOMAIN}:${YOOKASSA_PORT}/cryptobot-webhook"
echo -e "   Heleket:   https://${DOMAIN}:${YOOKASSA_PORT}/heleket-webhook"
echo -e "   Platega:   https://${DOMAIN}:${YOOKASSA_PORT}/platega-webhook"
echo -e "   TON:       https://${DOMAIN}:${YOOKASSA_PORT}/ton-webhook"
echo -e "   Р®Money:    https://${DOMAIN}:${YOOKASSA_PORT}/yoomoney-webhook"
echo ""
echo -e " ${BOLD}РќРѕРІРѕРµ РІ СЌС‚РѕР№ РІРµСЂСЃРёРё:${NC}"
echo -e "   вЂў Р“РёР±СЂРёРґРЅС‹Рµ РїРѕРґРїРёСЃРєРё Рё РґРѕРєСѓРїРєР° С‚СЂР°С„РёРєР° (WiFi/LTE, СЃРіРѕСЂР°РµРјС‹Рµ/РЅРµСЃРіРѕСЂР°РµРјС‹Рµ Р“Р‘)"
echo -e "     вЂ” РІРєР»СЋС‡Р°СЋС‚СЃСЏ per-host РІ Р°РґРјРёРЅРєРµ, РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РІС‹РєР»СЋС‡РµРЅС‹."
echo -e "   вЂў Fulfillment-РѕС‡РµСЂРµРґСЊ: РїРѕРІС‚РѕСЂРЅС‹Рµ webhook РЅРµ РІС‹РґР°СЋС‚ СѓСЃР»СѓРіСѓ РґРІР°Р¶РґС‹,"
echo -e "     РѕС€РёР±РєРё РїРѕСЃР»Рµ РѕРїР»Р°С‚С‹ СЂРµС‚СЂР°СЏС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё, Р·Р°С‚РµРј manual review."
echo -e "   вЂў Р‘СЌРєР°РїС‹ СЃРѕРґРµСЂР¶Р°С‚ СЃРЅРёРјРєРё СЃРѕСЃС‚РѕСЏРЅРёСЏ Remnawave (backup runs + snapshots)."
echo ""
echo -e " ${BOLD}SSL РЎРµСЂС‚РёС„РёРєР°С‚С‹:${NC}"
echo -e "   РџСѓР±Р»РёС‡РЅС‹Р№:  ${YELLOW}/etc/letsencrypt/live/${DOMAIN}/fullchain.pem${NC}"
echo -e "   РџСЂРёРІР°С‚РЅС‹Р№:  ${YELLOW}/etc/letsencrypt/live/${DOMAIN}/privkey.pem${NC}"
echo ""
echo -e "${YELLOW} вљ   РџРѕР¶Р°Р»СѓР№СЃС‚Р°, СЃРјРµРЅРёС‚Рµ РїР°СЂРѕР»СЊ СЃСЂР°Р·Сѓ РїРѕСЃР»Рµ РІС…РѕРґР°!${NC}"
echo ""
show_footer
