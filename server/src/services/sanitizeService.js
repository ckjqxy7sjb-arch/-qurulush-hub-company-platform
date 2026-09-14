import validator from "validator";

export function sanitizePlainText(value) {
  return validator.escape(validator.trim(String(value ?? "")));
}
