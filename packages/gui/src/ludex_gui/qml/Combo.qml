import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: box
    implicitHeight: 36
    font.family: Theme.family
    contentItem: Txt { leftPadding: 12; text: box.displayText; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
    background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: box.activeFocus ? 2 : 1; border.color: box.activeFocus ? Theme.accent : Theme.border }
    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: box.width
        contentItem: Txt { text: modelData }
        background: Rectangle { color: highlighted ? Theme.surface3 : Theme.surface2 }
        highlighted: box.highlightedIndex === index
    }
    popup.background: Rectangle { color: Theme.surface2; border.width: 1; border.color: Theme.border; radius: Theme.radius }
}
