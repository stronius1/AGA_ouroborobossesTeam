# Принимаем список тегов из консоли через запятую.
# По умолчанию, если ничего не передали, таг назначается 'unknown'.
# Использование: TAGS='latest,версия.1,версия.2,...' docker buildx bake -f .docker/bake.hcl <target>
variable "tags" {
  type    = list(string)
  default = ["unknown"]
}

target "base" {
  context = "."
  dockerfile = ".docker/build/Dockerfile"
  args = {
    GITVERSE = "true"
  }
  no-cache = false
  attest = [
    "type=sbom,disabled=true"
  ]
}

target "docker_io" {
  inherits = ["base"]
  tags = [for t in tags : "seaf/seaf-archtool-core:${t}"]
}

target "gitverse_ru" {
  inherits = ["base"]
  tags = [for t in tags : "gitverse.ru/seafteam/seaf-archtool-core:${t}"]
}
