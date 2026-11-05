{ ... }: {
  fleet.vms.rocker-frost.modules = [
    (
      {
        config,
        pkgs,
        ...
      }:
      let
        startScript = ''
          #!/bin/bash
          set -Eeuo pipefail

          site=/var/gerrit
          marker="$site/data/.cloud-vm-initialized"
          config="$site/etc/gerrit.config"
          all_projects="$site/git/All-Projects.git"
          all_users="$site/git/All-Users.git"
          runtime_directories=(
            "$site/git"
            "$site/index"
            "$site/cache"
            "$site/db"
            "$site/data"
            "$site/logs"
          )

          if [[ -e "$marker" ]]; then
            [[ -f "$marker" ]] || {
              echo "Gerrit initialization marker is not a regular file" >&2
              exit 1
            }
            [[ -f "$config" && -d "$all_projects" && -d "$all_users" ]] || {
              echo "Gerrit initialization marker exists but required site files are missing" >&2
              exit 1
            }
          else
            shopt -s dotglob nullglob
            for directory in "''${runtime_directories[@]}"; do
              entries=("$directory"/*)
              if (( ''${#entries[@]} )); then
                echo "Gerrit site data exists without its initialization marker; refusing to modify it" >&2
                exit 1
              fi
            done

            [[ ! -e "$all_projects" && ! -e "$all_users" ]] || {
              echo "Gerrit repositories exist without the initialization marker; refusing to modify them" >&2
              exit 1
            }
            for sensitive in "$site/etc/secure.config" "$site"/etc/ssh*; do
              [[ ! -e "$sensitive" ]] || {
                echo "Gerrit sensitive configuration exists without the initialization marker; refusing to modify it" >&2
                exit 1
              }
            done

            /entrypoint.sh init
            [[ -f "$config" && -d "$all_projects" && -d "$all_users" ]] || {
              echo "Gerrit initialization did not create the required site files" >&2
              exit 1
            }
          fi

          git config -f "$config" auth.type HTTP
          git config -f "$config" auth.httpHeader Authorization
          git config -f "$config" auth.trustContainerAuth true
          [[ "$(git config -f "$config" --get auth.type)" == HTTP ]]
          [[ "$(git config -f "$config" --get auth.httpHeader)" == Authorization ]]
          [[ "$(git config -f "$config" --get auth.trustContainerAuth)" == true ]]

          if [[ ! -e "$marker" ]]; then
            marker_tmp="$marker.tmp.$$"
            printf '%s\n' 'cloud-vm Gerrit site initialized' > "$marker_tmp"
            mv "$marker_tmp" "$marker"
          fi

          exec /entrypoint.sh
        '';
        nginxConfig = ''
          user nginx;
          worker_processes auto;
          error_log /var/log/nginx/error.log warn;
          pid /var/run/nginx.pid;

          events {
            worker_connections 1024;
          }

          http {
            include /etc/nginx/mime.types;
            default_type application/octet-stream;
            sendfile on;
            client_max_body_size 0;

            server {
              listen 8080;
              server_name _;

              auth_basic "Gerrit";
              auth_basic_user_file /run/secrets/gerrit.htpasswd;

              location / {
                proxy_pass http://gerrit:8080;
                proxy_http_version 1.1;
                proxy_request_buffering off;
                proxy_set_header Authorization $http_authorization;
                proxy_set_header Host $http_host;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Host $http_host;
                proxy_set_header X-Forwarded-Proto https;
              }
            }
          }
        '';
      in
      {
        services.podman = {
          enable = true;
          autoUpdate.enable = false;

          networks.gerrit = { };

          volumes = {
            gerrit-git = { };
            gerrit-index = { };
            gerrit-cache = { };
            gerrit-db = { };
            gerrit-etc = { };
            gerrit-data = { };
            gerrit-logs = { };
          };

          containers.gerrit = {
            image = "docker.io/gerritcodereview/gerrit:3.14.5@sha256:09b8ad30e8b60c3a28e73dc51b1ab14ad0cd6a8d62e68769242f3396dd5f2c57";
            entrypoint = "/bin/bash";
            exec = "/run/gerrit-start.sh";
            network = "gerrit.network";
            networkAlias = [ "gerrit" ];
            environment = {
              CANONICAL_WEB_URL = "https://rocker-frost.exe.xyz/";
              HTTPD_LISTEN_URL = "proxy-https://*:8080/";
            };
            volumes = [
              "gerrit-git.volume:/var/gerrit/git"
              "gerrit-index.volume:/var/gerrit/index"
              "gerrit-cache.volume:/var/gerrit/cache"
              "gerrit-db.volume:/var/gerrit/db"
              "gerrit-etc.volume:/var/gerrit/etc"
              "gerrit-data.volume:/var/gerrit/data"
              "gerrit-logs.volume:/var/gerrit/logs"
              "${config.xdg.configHome}/gerrit/start.sh:/run/gerrit-start.sh:ro"
            ];
            extraConfig.Service.TimeoutStartSec = "30min";
          };

          containers.gerrit-proxy = {
            image = "docker.io/library/nginx:1.30.6-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949";
            network = "gerrit.network";
            ports = [ "127.0.0.1:8000:8080" ];
            volumes = [
              "${config.xdg.configHome}/gerrit/nginx.conf:/etc/nginx/nginx.conf:ro"
            ];
            extraPodmanArgs = [
              "--secret=gerrit-htpasswd,type=mount,target=/run/secrets/gerrit.htpasswd,mode=0444"
            ];
            extraConfig = {
              Unit = {
                Requires = "podman-gerrit.service";
                After = "podman-gerrit.service";
              };
              Service.TimeoutStartSec = "5min";
            };
          };
        };

        xdg.configFile = {
          "gerrit/start.sh".text = startScript;
          "gerrit/nginx.conf".text = nginxConfig;
        };

        home.packages = [ pkgs.apacheHttpd ];
      }
    )
  ];
}
