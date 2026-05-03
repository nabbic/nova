resource "null_resource" "build_layer" {
  triggers = {
    requirements = filemd5("${path.module}/lambda-layer/requirements.txt")
  }
  provisioner "local-exec" {
    command = "bash ${path.module}/lambda-layer/build.sh"
  }
}

resource "aws_lambda_layer_version" "shared" {
  filename            = "${path.module}/lambda-layer/layer.zip"
  # source_code_hash omitted intentionally: filebase64sha256 is evaluated at plan time
  # before null_resource.build_layer has run, causing an "inconsistent result" error
  # on first apply. Change detection is handled via null_resource triggers.
  layer_name          = "nova-factory-shared"
  compatible_runtimes = ["python3.12"]
  depends_on          = [null_resource.build_layer]
}
