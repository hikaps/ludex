import QtQuick

// A cover picture, or a generated tile (tint plus initials) until one exists.
Item {
    id: art
    property url source
    property string title
    property int seed: 0

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.tint(art.seed, 0.34) }
            GradientStop { position: 1.0; color: Theme.tint(art.seed + 3, 0.16) }
        }
        Txt {
            anchors.centerIn: parent
            text: Theme.initials(art.title)
            font.pixelSize: Math.max(14, art.width * 0.26)
            font.bold: true
            color: "#ffffff"
            opacity: 0.5
        }
    }
    Image {
        anchors.fill: parent
        source: art.source
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        sourceSize.width: 420
        opacity: status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
    }
}
