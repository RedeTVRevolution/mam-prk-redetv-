variable "florence_modelo" {
  description = "Modelo do Florence-2: base ou large (ADR 0008)"
  type        = string
  default     = "base"
  validation {
    condition     = contains(["base", "large"], var.florence_modelo)
    error_message = "florence_modelo deve ser base ou large."
  }
}

variable "florence_feixes" {
  description = "Feixes da geração do Florence-2"
  type        = number
  default     = 1
  validation {
    condition     = var.florence_feixes >= 1 && floor(var.florence_feixes) == var.florence_feixes
    error_message = "florence_feixes deve ser um inteiro positivo."
  }
}

variable "florence_lote" {
  description = "Quadros por geração do Florence-2"
  type        = number
  default     = 16
  validation {
    condition     = var.florence_lote >= 1 && floor(var.florence_lote) == var.florence_lote
    error_message = "florence_lote deve ser um inteiro positivo."
  }
}

variable "florence_legendas" {
  description = "Legendas de região do Florence-2: 1 liga, 0 desliga"
  type        = number
  default     = 1
  validation {
    condition     = contains([0, 1], var.florence_legendas)
    error_message = "florence_legendas vale 0 ou 1."
  }
}
