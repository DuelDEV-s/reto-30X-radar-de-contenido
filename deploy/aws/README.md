# Despliegue en AWS (EC2)

Una sola máquina EC2 corre el `compose.yaml` del proyecto tal cual: PostgreSQL, API y web. Sin SSH: la administración va por AWS Systems Manager (SSM) y las claves se guardan cifradas en SSM Parameter Store.

| Pieza | Valor |
| --- | --- |
| Región | `us-east-2` |
| Máquina | `t3.small` (2 vCPU, 2 GB + 2 GB de swap), Ubuntu 24.04, disco gp3 de 25 GB cifrado |
| Red | Elastic IP; grupo de seguridad con solo 80 y 443 abiertos |
| Claves | `/radar30x/*` en SSM Parameter Store (SecureString) |
| Acceso | `APP_PIN` de 6 dígitos; nginx limita los intentos a 10 por minuto por IP |

Costo aproximado: unos US$21 al mes (máquina US$15, IPv4 US$3,65, disco US$2), cubiertos por los créditos del plan gratuito. Exa, Anthropic, OpenAI, Gemini y Bright Data se cobran aparte por uso.

## Requisitos

- AWS CLI v2 con el perfil `radar30x` de la cuenta del proyecto: `aws login --profile radar30x --region us-east-2`. Los scripts se niegan a correr si el perfil apunta a otra cuenta.
- Bash (Git Bash en Windows) y Python 3.

## Pasos

```bash
deploy/aws/provision.sh                          # infraestructura (una vez, ~5 min)
deploy/aws/secrets.sh ruta/al/.env               # claves → SSM; genera APP_PIN y la contraseña de PostgreSQL
deploy/aws/deploy.sh                             # trae main de GitHub y levanta los contenedores (~8 min la primera vez)
```

Para actualizar después de un merge a `main`, basta con volver a correr `deploy/aws/deploy.sh`. Para cambiar una clave, `secrets.sh` con el archivo nuevo y luego `deploy.sh`.

`secrets.sh` acepta varios archivos; cada uno pisa al anterior, por ejemplo `.env.example` (valores no secretos como los dataset IDs), luego los `.env` con claves. Los valores vacíos se ignoran. Nunca se suben `DATABASE_URL`, `CORS_ORIGINS`, `TRENDS_DB_PATH` ni `POSTGRES_*`: la base de datos la gestiona el despliegue (usuario y base `radar`, contraseña generada) y Compose arma `DATABASE_URL` con esos valores. PostgreSQL conserva los datos con los que se creó, así que cambiarlos después dejaría a la API sin acceso.

## Operación

- Consola en la máquina: `aws ssm start-session --target <instance-id> --profile radar30x --region us-east-2` (requiere el Session Manager plugin).
- Ver el PIN: `aws ssm get-parameter --name /radar30x/APP_PIN --with-decryption --profile radar30x --region us-east-2`.
- Apagar para no gastar: `aws ec2 stop-instances` (la IP elástica se conserva; mientras está apagada solo se cobran el disco y la IP).
- Borrar todo: `deploy/aws/teardown.sh` (agregar `--with-secrets` para borrar también las claves). La base de datos vive en el disco de la máquina y se borra con ella.

## HTTPS

Por defecto la app se sirve por HTTP en la IP elástica. Para HTTPS hace falta un dominio propio apuntando a esa IP (un proxy como Caddy obtiene el certificado solo), o poner CloudFront delante: da una URL `*.cloudfront.net` con HTTPS sin dominio, pero corta las peticiones que tardan más de 60 s.
