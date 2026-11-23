import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Title matches the import was not sure about: join the game to one it may be, or keep them apart.
Dialog {
    id: dialog
    objectName: "reviewDialog"
    readonly property var item: backend.review.length > 0 ? backend.review[0] : null

    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(640, Overlay.overlay ? Overlay.overlay.width - 48 : 640)
    padding: 20
    background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
    header: Txt {
        text: "Review matches" + (backend.review.length > 0 ? "  (" + backend.review.length + " left)" : "")
        font.bold: true
        font.pixelSize: 18
        padding: 20
        bottomPadding: 0
    }
    // Land on the first answer of the item shown, also after one was answered and the next appears.
    function focusAnswer() {
        (choices.count > 0 ? choices.itemAt(0) : closeButton).forceActiveFocus(Qt.TabFocusReason)
    }
    onItemChanged: if (visible) { if (item === null) close(); else Qt.callLater(focusAnswer) }
    onOpened: Qt.callLater(focusAnswer)

    contentItem: ColumnLayout {
        spacing: 10
        Txt {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            visible: dialog.item !== null
            text: dialog.item ? "“" + dialog.item.title + "” from " + dialog.item.store + " (" + dialog.item.account + ") may be the same game as:" : ""
        }
        Repeater {
            id: choices
            model: dialog.item ? dialog.item.candidates : []
            delegate: Btn {
                id: candidate
                required property var modelData
                required property int index
                objectName: "mergeInto-" + modelData.id
                Layout.fillWidth: true
                implicitHeight: 48
                primary: index === 0
                text: "Same game as “" + modelData.title + "”" + (modelData.stores !== "" ? "  (" + modelData.stores + ")" : "")
                onClicked: backend.mergeReview(dialog.item.gameId, modelData.id)
            }
        }
        Btn {
            objectName: "keepSeparate"
            Layout.fillWidth: true
            implicitHeight: 48
            visible: dialog.item !== null
            text: "Different game: keep them apart"
            onClicked: backend.keepSeparate(dialog.item.id)
        }
        Txt {
            Layout.fillWidth: true
            visible: dialog.item === null
            color: Theme.muted
            text: "Nothing to review"
        }
    }

    footer: RowLayout {
        Item { Layout.fillWidth: true }
        Btn { id: closeButton; text: "Close"; onClicked: dialog.close() }
        Item { Layout.preferredWidth: 12 }
    }
}
