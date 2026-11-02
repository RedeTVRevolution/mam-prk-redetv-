#!/bin/sh
# Alvos `ocr` e `ocr-gpu` do Dockerfile: baixa para /modelos o detector pedido (`$1`) e o
# reconhecedor, nas revisões fixadas, e confere o SHA-256 de cada arquivo. O detector é
# escolhido pelo ARG do alvo; os dois aceitos estão aqui, e um nome outro falha. Só o
# urllib do Python da imagem base: a imagem não tem curl.
set -eu

RECONHECEDOR=latin_PP-OCRv5_mobile_rec
RECONHECEDOR_REVISAO=ab2cd5cc5fa6309be2e5acdfe66eca2c2c127d57

case "$1" in
PP-OCRv5_server_det)
    DETECTOR_REVISAO=ca867c897ecbca8873081573a802ad70d499cb94
    HASHES="183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d inference.pdiparams
436bf19010fe3879477e8599a870a0ec8ccd14ca39056805ec4ed20ab318ec04 config.json
af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28 inference.json
28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685 inference.yml"
    ;;
PP-OCRv5_mobile_det)
    DETECTOR_REVISAO=0d63e78e2b680928f6b1747d76a08db6e645efb7
    HASHES="afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b inference.pdiparams
7ac1c33f377ba58561f4b89d3180b6add2b7c5c60a4edac90fa4e0ceccdc6665 config.json
05feef1acb00aa4cd7362b15f7f501fc4f99d7b1fa73c1c871e0c7b1504b0f5c inference.json
98069072e1b6b37d727fd9d9f11725faa46d6ea0de012f2ed26caea011c37699 inference.yml"
    ;;
*)
    echo "Detector desconhecido: $1 (PP-OCRv5_server_det ou PP-OCRv5_mobile_det)" >&2
    exit 1
    ;;
esac

baixar() {
    mkdir -p "/modelos/$1"
    for arquivo in config.json inference.json inference.pdiparams inference.yml; do
        python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
            "https://huggingface.co/PaddlePaddle/$1/resolve/$2/$arquivo" "/modelos/$1/$arquivo"
    done
}

baixar "$1" "$DETECTOR_REVISAO"
baixar "$RECONHECEDOR" "$RECONHECEDOR_REVISAO"
echo "$HASHES" | while read -r hash arquivo; do
    echo "$hash  /modelos/$1/$arquivo"
done >/tmp/hashes
cat >>/tmp/hashes <<HASHES_DO_RECONHECEDOR
53cdc8b481a7394bb108f96d0fb3432b0a8f392e22c7d18f06dbb2d42b8b25f9  /modelos/$RECONHECEDOR/inference.pdiparams
e0f5ccc44fe86254956f27746058bc4cf88d86145668cecf22ba5dd962483c80  /modelos/$RECONHECEDOR/config.json
820b2ee8e5072de5156c3d55124c2b03c82ef278d59f453f857c0789bacb4da1  /modelos/$RECONHECEDOR/inference.json
0bbe984570f597af3638e50bdf2e8276f3ab26a61966096538b3b0d1849f5c84  /modelos/$RECONHECEDOR/inference.yml
HASHES_DO_RECONHECEDOR
sha256sum -c /tmp/hashes
rm /tmp/hashes
