using System;
using System.Collections;
using System.Runtime.Serialization.Formatters.Binary;

public class Legacy
{
    public void Collect()
    {
        ArrayList list = new ArrayList();
        Hashtable map = new Hashtable();
        Stack stack = new Stack();
        BinaryFormatter formatter = new BinaryFormatter();
        Console.WriteLine(list.Count + map.Count + stack.Count + formatter.ToString());
    }
}
