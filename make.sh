#!/bin/bash

# Проверка на root-права
if [[ $EUID -ne 0 ]]; then
    echo "Этот скрипт должен быть запущен с правами суперпользователя."
    exit 1
fi

# Установка 3x-ui
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)

# Генерация рандомного пароля для администратора 3x-ui
ADMIN_PASSWORD=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 12)
echo "Admin password for 3x-ui: $ADMIN_PASSWORD"

# Настройка 3x-ui с логином admin и рандомным паролем
/usr/local/x-ui/x-ui setting -username admin -password $ADMIN_PASSWORD -port 2053
echo "3x-ui has been configured with username 'admin' and the specified password on port 2053."

# Настройка UFW
ufw default deny incoming
ufw default allow outgoing
ufw allow 80
ufw allow 443
ufw allow from 127.0.0.1 to any port 2053
ufw allow from 146.190.225.169 to any port 2053
ufw allow ssh

# Генерация рандомного порта для SSH от 50000 до 65535
NEW_SSH_PORT=$(shuf -i 50000-65535 -n 1)
echo "SSH port: $NEW_SSH_PORT"

# Изменение порта SSH
sed -i "/^Port 22/c\Port $NEW_SSH_PORT" /etc/ssh/sshd_config
ufw allow $NEW_SSH_PORT
ufw delete allow 22
systemctl restart sshd

# Генерация рандомного пароля для SSH
SSH_PASSWORD=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 12)
echo "SSH password: $SSH_PASSWORD"

# Изменение пароля пользователя root
echo "root:$SSH_PASSWORD" | chpasswd

# Включение UFW
ufw enable

# Вывод информации
echo "Installation and configuration complete."
echo "3x-ui is accessible at port 2053 with username 'admin' and password: $ADMIN_PASSWORD"
echo "SSH is accessible at port $NEW_SSH_PORT with password: $SSH_PASSWORD"