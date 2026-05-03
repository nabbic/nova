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
  # source_code_hash uses the requirements.txt md5 (same value the build_layer
  # null_resource triggers on). This avoids the filebase64sha256 plan-vs-apply
  # race while still publishing a new layer version when deps change.
  source_code_hash    = filemd5("${path.module}/lambda-layer/requirements.txt")
  layer_name          = "nova-factory-shared"
  compatible_runtimes = ["python3.12"]
  depends_on          = [null_resource.build_layer]
}
