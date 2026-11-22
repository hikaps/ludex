import QtQuick

// The ludex icon. A fixed raster size (the layouts size the item), so the size never depends on the image.
Image {
    objectName: "logo"
    source: backend.logo
    sourceSize: Qt.size(96, 96)
    fillMode: Image.PreserveAspectFit
    smooth: true
    asynchronous: true
}
